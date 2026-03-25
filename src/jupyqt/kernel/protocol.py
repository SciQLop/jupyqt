"""Jupyter wire protocol handler for jupyqt.

Dispatches incoming Jupyter messages to handlers and publishes
results/output on the iopub channel. When a KernelThread is provided,
cell execution is dispatched to it via run_sync(). Without one (unit
tests), execution runs directly in the current thread.
"""

from __future__ import annotations

import builtins
import math
import sys
import threading
import traceback
from typing import TYPE_CHECKING, Any

import anyio
from IPython.core.completer import provisionalcompleter

from jupyqt.kernel.comm import CommManager, get_comm_manager, set_current_parent, set_publish_fn
from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.kernel.shell import DisplayCapture, OutputCapture, encode_display_data

if TYPE_CHECKING:
    from collections.abc import Callable

    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from IPython.core.interactiveshell import InteractiveShell

    from jupyqt.kernel.thread import KernelThread


def _get_version() -> str:
    try:
        from importlib.metadata import version  # noqa: PLC0415
        return version("jupyqt")
    except Exception:  # noqa: BLE001
        return "0.0.0"


class KernelProtocol:
    """Handles Jupyter wire protocol messages using an InteractiveShell."""

    def __init__(
        self,
        shell: InteractiveShell,
        key: str = "0",
        kernel_thread: KernelThread | None = None,
    ) -> None:
        """Set up the protocol handler with the given shell and optional kernel thread."""
        self._shell = shell
        self._key = key
        self._kernel_thread = kernel_thread
        self._execution_count = 0
        self._comm_manager: CommManager = get_comm_manager()
        self._iopub_send: MemoryObjectSendStream[list[bytes]]
        self._iopub_recv: MemoryObjectReceiveStream[list[bytes]]
        self._iopub_send, self._iopub_recv = anyio.create_memory_object_stream[list[bytes]](
            max_buffer_size=math.inf,
        )
        self._stdin_send: MemoryObjectSendStream[list[bytes]]
        self._stdin_recv: MemoryObjectReceiveStream[list[bytes]]
        self._stdin_send, self._stdin_recv = anyio.create_memory_object_stream[list[bytes]](
            max_buffer_size=math.inf,
        )
        self._stdin_reply_send: MemoryObjectSendStream[str]
        self._stdin_reply_recv: MemoryObjectReceiveStream[str]
        self._stdin_reply_send, self._stdin_reply_recv = anyio.create_memory_object_stream[str](
            max_buffer_size=1,
        )
        self._stdin_reply_event = threading.Event()
        self._stdin_reply_value: str = ""
        set_publish_fn(self._publish_comm)
        self._handlers = {
            "kernel_info_request": self._handle_kernel_info,
            "execute_request": self._handle_execute,
            "complete_request": self._handle_complete,
            "inspect_request": self._handle_inspect,
            "is_complete_request": self._handle_is_complete,
            "shutdown_request": self._handle_shutdown,
            "history_request": self._handle_history,
            "comm_info_request": self._handle_comm_info,
            "comm_open": self._handle_comm_open,
            "comm_msg": self._handle_comm_msg,
            "comm_close": self._handle_comm_close,
        }

    @property
    def iopub_receive(self) -> MemoryObjectReceiveStream[list[bytes]]:
        """Stream of serialized iopub messages produced by this protocol."""
        return self._iopub_recv

    @property
    def stdin_receive(self) -> MemoryObjectReceiveStream[list[bytes]]:
        """Stream of serialized stdin request messages (input_request)."""
        return self._stdin_recv

    def supply_stdin_reply(self, value: str) -> None:
        """Provide a reply to a pending input_request (called from stdin channel)."""
        self._stdin_reply_value = value
        self._stdin_reply_event.set()

    async def handle_message(self, channel: str, raw_msg: list[bytes]) -> list[bytes] | None:  # noqa: ARG002
        """Deserialize, dispatch, and serialize a Jupyter wire protocol message."""
        _, parts = feed_identities(raw_msg)
        msg = deserialize_message(parts)
        msg_type = msg["msg_type"]
        handler = self._handlers.get(msg_type)
        if handler is None:
            reply = create_message(
                msg_type.replace("_request", "_reply"),
                parent=msg,
                content={
                    "status": "error",
                    "ename": "NotImplementedError",
                    "evalue": f"Unknown: {msg_type}",
                    "traceback": [],
                },
            )
            return serialize_message(reply, self._key)
        await self._publish_status("busy", msg)
        reply = await handler(msg)
        await self._publish_status("idle", msg)
        if reply is None:
            return None
        return serialize_message(reply, self._key)

    def _raw_input(self, prompt: str = "", parent: dict[str, Any] | None = None) -> str:
        """Send input_request on stdin and block until reply arrives.

        Called from the kernel thread (via patched builtins.input) so it must
        use thread-safe synchronisation, not async.
        """
        parent = parent or {}
        msg = create_message(
            "input_request",
            parent=parent,
            content={"prompt": prompt, "password": False},
        )
        self._stdin_reply_event.clear()
        self._stdin_send.send_nowait(serialize_message(msg, self._key))
        self._stdin_reply_event.wait()
        return self._stdin_reply_value

    async def _publish_status(self, status: str, parent: dict[str, Any]) -> None:
        msg = create_message("status", parent=parent, content={"execution_state": status})
        await self._iopub_send.send(serialize_message(msg, self._key))

    async def _publish_stream(self, name: str, text: str, parent: dict[str, Any]) -> None:
        msg = create_message("stream", parent=parent, content={"name": name, "text": text})
        await self._iopub_send.send(serialize_message(msg, self._key))

    async def _handle_kernel_info(self, msg: dict[str, Any]) -> dict[str, Any]:
        return create_message(
            "kernel_info_reply",
            parent=msg,
            content={
                "status": "ok",
                "protocol_version": "5.4",
                "implementation": "jupyqt",
                "implementation_version": _get_version(),
                "language_info": {
                    "name": "python",
                    "version": sys.version.split()[0],
                    "mimetype": "text/x-python",
                    "file_extension": ".py",
                    "pygments_lexer": "ipython3",
                    "codemirror_mode": {"name": "ipython", "version": 3},
                    "nbconvert_exporter": "python",
                },
                "banner": f"jupyqt kernel (Python {sys.version})",
                "help_links": [],
            },
        )

    def _publish_comm(
        self, msg_type: str, content: dict[str, Any], parent: dict[str, Any],
    ) -> None:
        """Publish a comm message on iopub (may be called from any thread)."""
        msg = create_message(msg_type, parent=parent, content=content)
        self._iopub_send.send_nowait(serialize_message(msg, self._key))

    async def _handle_execute(self, msg: dict[str, Any]) -> dict[str, Any]:
        set_current_parent(msg)
        content = msg["content"]
        code = content["code"]
        silent = content.get("silent", False)
        allow_stdin = content.get("allow_stdin", False)

        if not silent:
            self._execution_count += 1

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        captured_error: dict[str, Any] | None = None
        display_capture = DisplayCapture(self._shell)
        original_showtraceback = self._shell.showtraceback

        def _capture_traceback(*_args: Any, **_kwargs: Any) -> None:
            nonlocal captured_error
            etype, evalue, tb = sys.exc_info()
            if etype is not None:
                captured_error = {
                    "ename": etype.__name__,
                    "evalue": str(evalue),
                    "traceback": traceback.format_exception(etype, evalue, tb),
                }

        def _patched_input(prompt: str = "") -> str:
            return self._raw_input(prompt, parent=msg)

        async def _execute_async() -> Any:
            self._shell.showtraceback = _capture_traceback  # ty: ignore[invalid-assignment]
            original_input = builtins.input
            if allow_stdin:
                builtins.input = _patched_input  # ty: ignore[invalid-assignment]
            capture = OutputCapture(
                on_stdout=stdout_chunks.append,
                on_stderr=stderr_chunks.append,
            )
            try:
                with display_capture, capture:
                    return await self._shell.run_cell_async(
                        code, store_history=not silent, silent=silent,
                    )
            finally:
                self._shell.showtraceback = original_showtraceback
                builtins.input = original_input

        def _execute_sync() -> Any:
            self._shell.showtraceback = _capture_traceback  # ty: ignore[invalid-assignment]
            original_input = builtins.input
            if allow_stdin:
                builtins.input = _patched_input  # ty: ignore[invalid-assignment]
            capture = OutputCapture(
                on_stdout=stdout_chunks.append,
                on_stderr=stderr_chunks.append,
            )
            try:
                with display_capture, capture:
                    return self._shell.run_cell(code, store_history=not silent, silent=silent)
            finally:
                self._shell.showtraceback = original_showtraceback
                builtins.input = original_input

        if self._kernel_thread is not None:
            result = await anyio.to_thread.run_sync(  # ty: ignore[unresolved-attribute]
                lambda: self._kernel_thread.run_coroutine(_execute_async()),  # ty: ignore[unresolved-attribute]
            )
        else:
            result = _execute_sync()

        if stdout_chunks:
            await self._publish_stream("stdout", "".join(stdout_chunks), msg)
        if stderr_chunks:
            await self._publish_stream("stderr", "".join(stderr_chunks), msg)

        for display_output in display_capture.outputs:
            display_msg = create_message(
                "display_data",
                parent=msg,
                content={
                    "data": display_output["data"],
                    "metadata": display_output["metadata"],
                    "transient": display_output["transient"],
                },
            )
            await self._iopub_send.send(serialize_message(display_msg, self._key))

        if result.result is not None and not silent:
            format_dict, md_dict = self._shell.display_formatter.format(result.result)  # ty: ignore[unresolved-attribute]
            exec_result_msg = create_message(
                "execute_result",
                parent=msg,
                content={
                    "execution_count": self._execution_count,
                    "data": encode_display_data(format_dict),
                    "metadata": md_dict,
                },
            )
            await self._iopub_send.send(serialize_message(exec_result_msg, self._key))

        error_info = captured_error
        if error_info is None and result.error_in_exec is not None:
            error_info = {
                "ename": type(result.error_in_exec).__name__,
                "evalue": str(result.error_in_exec),
                "traceback": traceback.format_exception(
                    type(result.error_in_exec),
                    result.error_in_exec,
                    result.error_in_exec.__traceback__,
                ),
            }

        if error_info is not None:
            error_content = {
                "status": "error",
                **error_info,
                "execution_count": self._execution_count,
            }
            error_msg = create_message("error", parent=msg, content=error_content)
            await self._iopub_send.send(serialize_message(error_msg, self._key))
            return create_message("execute_reply", parent=msg, content=error_content)

        return create_message(
            "execute_reply",
            parent=msg,
            content={
                "status": "ok",
                "execution_count": self._execution_count,
                "user_expressions": {},
            },
        )

    async def _run_on_shell(self, func: Callable[..., Any], *args: Any) -> Any:
        """Run func on the kernel thread if available, else directly."""
        if self._kernel_thread is not None:
            return await anyio.to_thread.run_sync(  # ty: ignore[unresolved-attribute]
                lambda: self._kernel_thread.run_sync(func, *args),  # ty: ignore[unresolved-attribute]
            )
        return func(*args)

    async def _handle_complete(self, msg: dict[str, Any]) -> dict[str, Any]:
        content = msg["content"]
        code = content["code"]
        cursor_pos = content["cursor_pos"]

        def _do_complete() -> tuple[list[str], int]:
            with provisionalcompleter():
                completions = list(self._shell.Completer.completions(code, cursor_pos))
            matches = [c.text for c in completions]
            cursor_start = completions[0].start if completions else cursor_pos
            return matches, cursor_start

        matches, cursor_start = await self._run_on_shell(_do_complete)
        return create_message(
            "complete_reply",
            parent=msg,
            content={
                "status": "ok",
                "matches": matches,
                "cursor_start": cursor_start,
                "cursor_end": cursor_pos,
                "metadata": {},
            },
        )

    async def _handle_inspect(self, msg: dict[str, Any]) -> dict[str, Any]:
        content = msg["content"]
        code = content["code"]
        cursor_pos = content["cursor_pos"]
        detail_level = content.get("detail_level", 0)
        name = code[:cursor_pos].split()[-1] if code[:cursor_pos].strip() else ""

        def _do_inspect() -> tuple[bool, dict[str, Any]]:
            try:
                info = self._shell.object_inspect(name, detail_level=detail_level)
                found = info.get("found", False)
                data = {}
                if found:
                    text_parts = []
                    if info.get("type_name"):
                        text_parts.append(f"Type: {info['type_name']}")
                    if info.get("string_form"):
                        text_parts.append(f"String form: {info['string_form']}")
                    if info.get("docstring"):
                        text_parts.append(info["docstring"])
                    data["text/plain"] = "\n".join(text_parts) if text_parts else str(info)
                return found, data
            except Exception:  # noqa: BLE001
                return False, {}
            else:
                return found, data

        found, data = await self._run_on_shell(_do_inspect)
        return create_message(
            "inspect_reply",
            parent=msg,
            content={"status": "ok", "found": found, "data": data, "metadata": {}},
        )

    async def _handle_is_complete(self, msg: dict[str, Any]) -> dict[str, Any]:
        code = msg["content"]["code"]

        def _do_check() -> tuple[str, str]:
            return self._shell.input_transformer_manager.check_complete(code)

        result = await self._run_on_shell(_do_check)
        status = result[0]
        indent = result[1] if len(result) > 1 else ""
        reply_content = {"status": status}
        if status == "incomplete":
            reply_content["indent"] = indent or ""
        return create_message("is_complete_reply", parent=msg, content=reply_content)

    async def _handle_comm_info(self, msg: dict[str, Any]) -> dict[str, Any]:
        target_name = msg["content"].get("target_name") or None
        return create_message(
            "comm_info_reply",
            parent=msg,
            content={"status": "ok", "comms": self._comm_manager.comm_info(target_name)},
        )

    async def _handle_comm_open(self, msg: dict[str, Any]) -> None:
        set_current_parent(msg)
        await self._run_on_shell(self._comm_manager.handle_comm_open, msg)

    async def _handle_comm_msg(self, msg: dict[str, Any]) -> None:
        set_current_parent(msg)
        await self._run_on_shell(self._comm_manager.handle_comm_msg, msg)

    async def _handle_comm_close(self, msg: dict[str, Any]) -> None:
        set_current_parent(msg)
        await self._run_on_shell(self._comm_manager.handle_comm_close, msg)

    async def _handle_shutdown(self, msg: dict[str, Any]) -> dict[str, Any]:
        restart = msg["content"].get("restart", False)
        return create_message(
            "shutdown_reply",
            parent=msg,
            content={"status": "ok", "restart": restart},
        )

    async def _handle_history(self, msg: dict[str, Any]) -> dict[str, Any]:
        return create_message(
            "history_reply",
            parent=msg,
            content={"status": "ok", "history": []},
        )
