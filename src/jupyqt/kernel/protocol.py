"""Jupyter wire protocol handler for jupyqt.

Dispatches incoming Jupyter messages to handlers and publishes
results/output on the iopub channel. When a KernelThread is provided,
cell execution is dispatched to it via run_sync(). Without one (unit
tests), execution runs directly in the current thread.
"""

from __future__ import annotations

import math
import sys
import traceback
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.kernel.shell import OutputCapture
from jupyqt.kernel.thread import KernelThread


class KernelProtocol:
    """Handles Jupyter wire protocol messages using an InteractiveShell."""

    def __init__(
        self,
        shell: InteractiveShell,
        key: str = "0",
        kernel_thread: KernelThread | None = None,
    ) -> None:
        self._shell = shell
        self._key = key
        self._kernel_thread = kernel_thread
        self._execution_count = 0
        self._iopub_send: MemoryObjectSendStream[list[bytes]]
        self._iopub_recv: MemoryObjectReceiveStream[list[bytes]]
        self._iopub_send, self._iopub_recv = anyio.create_memory_object_stream[list[bytes]](
            max_buffer_size=math.inf
        )
        self._handlers = {
            "kernel_info_request": self._handle_kernel_info,
            "execute_request": self._handle_execute,
            "complete_request": self._handle_complete,
            "inspect_request": self._handle_inspect,
            "is_complete_request": self._handle_is_complete,
            "shutdown_request": self._handle_shutdown,
            "history_request": self._handle_history,
        }

    @property
    def iopub_receive(self) -> MemoryObjectReceiveStream[list[bytes]]:
        return self._iopub_recv

    async def handle_message(self, channel: str, raw_msg: list[bytes]) -> list[bytes]:
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
        serialized = serialize_message(reply, self._key)
        await self._publish_status("idle", msg)
        return serialized

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
                "implementation_version": "0.1.0",
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

    async def _handle_execute(self, msg: dict[str, Any]) -> dict[str, Any]:
        content = msg["content"]
        code = content["code"]
        silent = content.get("silent", False)

        if not silent:
            self._execution_count += 1

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        captured_error: dict[str, Any] | None = None
        original_showtraceback = self._shell.showtraceback

        def _capture_traceback(*args, **kwargs):
            nonlocal captured_error
            etype, evalue, tb = sys.exc_info()
            if etype is not None:
                captured_error = {
                    "ename": etype.__name__,
                    "evalue": str(evalue),
                    "traceback": traceback.format_exception(etype, evalue, tb),
                }

        def _execute():
            self._shell.showtraceback = _capture_traceback
            capture = OutputCapture(
                on_stdout=lambda text: stdout_chunks.append(text),
                on_stderr=lambda text: stderr_chunks.append(text),
            )
            try:
                with capture:
                    return self._shell.run_cell(code, store_history=not silent, silent=silent)
            finally:
                self._shell.showtraceback = original_showtraceback

        if self._kernel_thread is not None:
            result = self._kernel_thread.run_sync(_execute)
        else:
            result = _execute()

        if stdout_chunks:
            await self._publish_stream("stdout", "".join(stdout_chunks), msg)
        if stderr_chunks:
            await self._publish_stream("stderr", "".join(stderr_chunks), msg)

        if result.result is not None and not silent:
            exec_result_msg = create_message(
                "execute_result",
                parent=msg,
                content={
                    "execution_count": self._execution_count,
                    "data": {"text/plain": repr(result.result)},
                    "metadata": {},
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

    async def _handle_complete(self, msg: dict[str, Any]) -> dict[str, Any]:
        content = msg["content"]
        code = content["code"]
        cursor_pos = content["cursor_pos"]
        completions = list(self._shell.Completer.completions(code, cursor_pos))
        matches = [c.text for c in completions]
        cursor_start = completions[0].start if completions else cursor_pos
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
        except Exception:
            found = False
            data = {}
        return create_message(
            "inspect_reply",
            parent=msg,
            content={"status": "ok", "found": found, "data": data, "metadata": {}},
        )

    async def _handle_is_complete(self, msg: dict[str, Any]) -> dict[str, Any]:
        code = msg["content"]["code"]
        result = self._shell.input_transformer_manager.check_complete(code)
        status = result[0]
        indent = result[1] if len(result) > 1 else ""
        reply_content = {"status": status}
        if status == "incomplete":
            reply_content["indent"] = indent or ""
        return create_message("is_complete_reply", parent=msg, content=reply_content)

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
