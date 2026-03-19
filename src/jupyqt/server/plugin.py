"""Jupyverse kernel plugin for jupyqt.

Provides a Kernel implementation that wires jupyverse's memory streams
to our KernelProtocol. When jupyverse is not installed, JupyQtKernel
creates its own streams for testing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import anyio
from anyio.streams.stapled import StapledObjectStream

from jupyqt.kernel.messages import deserialize_message, feed_identities
from jupyqt.kernel.protocol import KernelProtocol

if TYPE_CHECKING:
    from anyio.abc import TaskStatus
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from IPython.core.interactiveshell import InteractiveShell

    from jupyqt.kernel.thread import KernelThread

try:
    from jupyverse_kernel import DefaultKernelFactory, Kernel, KernelFactory

    HAS_JUPYVERSE = True
except ImportError:
    HAS_JUPYVERSE = False


_IGNORED = object()


class JupyQtKernel:
    """Kernel that processes Jupyter messages using an InteractiveShell.

    Creates its own anyio memory streams (same layout as jupyverse_kernel.Kernel).
    Used directly in tests; the jupyverse-compatible subclass is created by
    create_jupyqt_kernel_class().
    """

    def __init__(
        self,
        shell: InteractiveShell,
        kernel_thread: KernelThread | None = None,
        **_kwargs: Any,
    ) -> None:
        """Set up in-process streams and a KernelProtocol for the given shell."""
        self._shell = shell
        self._kernel_thread = kernel_thread
        self.key = "0"
        self._protocol = KernelProtocol(shell, key=self.key, kernel_thread=kernel_thread)
        self._task_group: anyio.abc.TaskGroup | None = None

        self._to_shell_send, self._to_shell_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_shell_send, self._from_shell_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._to_control_send, self._to_control_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_control_send, self._from_control_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._to_stdin_send, self._to_stdin_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_stdin_send, self._from_stdin_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_iopub_send, self._from_iopub_recv = anyio.create_memory_object_stream[list[bytes]](
            max_buffer_size=math.inf,
        )

        self._shell_stream = StapledObjectStream(self._to_shell_send, self._from_shell_recv)
        self._control_stream = StapledObjectStream(self._to_control_send, self._from_control_recv)
        self._stdin_stream = StapledObjectStream(self._to_stdin_send, self._from_stdin_recv)

    @property
    def shell_stream(self) -> StapledObjectStream:
        """Stapled stream for shell-channel communication."""
        return self._shell_stream

    @property
    def control_stream(self) -> StapledObjectStream:
        """Stapled stream for control-channel communication."""
        return self._control_stream

    @property
    def stdin_stream(self) -> StapledObjectStream:
        """Stapled stream for stdin-channel communication."""
        return self._stdin_stream

    @property
    def iopub_stream(self) -> MemoryObjectReceiveStream:
        """Receive stream for iopub messages published by the protocol."""
        return self._from_iopub_recv

    async def start(self, *, task_status: Any = _IGNORED) -> None:
        """Start dispatching messages; signal task_status when ready."""
        async with anyio.create_task_group() as tg:
            self._task_group = tg
            tg.start_soon(self._dispatch_channel, self._to_shell_recv, self._from_shell_send)
            tg.start_soon(self._dispatch_channel, self._to_control_recv, self._from_control_send)
            tg.start_soon(self._forward_iopub)
            tg.start_soon(self._forward_stdin_requests)
            tg.start_soon(self._forward_stdin_replies)
            if task_status is not _IGNORED:
                task_status.started()
            await anyio.sleep_forever()

    async def stop(self) -> None:
        """Cancel the task group to stop all dispatch loops."""
        if self._task_group:
            self._task_group.cancel_scope.cancel()

    async def interrupt(self) -> None:
        """Interrupt the running cell on the kernel thread."""
        if self._kernel_thread is not None:
            self._kernel_thread.interrupt()

    async def _dispatch_channel(
        self,
        recv_stream: MemoryObjectReceiveStream,
        send_stream: MemoryObjectSendStream,
    ) -> None:
        async for raw_msg in recv_stream:
            reply = await self._protocol.handle_message("shell", raw_msg)
            if reply is not None:
                await send_stream.send(reply)

    async def _forward_iopub(self) -> None:
        async for raw_msg in self._protocol.iopub_receive:
            await self._from_iopub_send.send(raw_msg)

    async def _forward_stdin_requests(self) -> None:
        """Forward input_request messages from protocol to the frontend."""
        async for raw_msg in self._protocol.stdin_receive:
            await self._from_stdin_send.send(raw_msg)

    async def _forward_stdin_replies(self) -> None:
        """Forward input_reply messages from the frontend to the protocol."""
        async for raw_msg in self._to_stdin_recv:
            _, parts = feed_identities(raw_msg)
            msg = deserialize_message(parts)
            if msg["msg_type"] == "input_reply":
                self._protocol.supply_stdin_reply(msg["content"].get("value", ""))


def create_jupyqt_kernel_class(
    shell: InteractiveShell,
    kernel_thread: KernelThread | None = None,
) -> type:
    """Create a Kernel subclass that inherits from jupyverse_kernel.Kernel.

    The class captures the shell and kernel_thread references via closure.
    """
    if not HAS_JUPYVERSE:
        raise ImportError("jupyverse is required")

    class _JupyQtJupyverseKernel(Kernel):
        def __init__(self, **_kwargs: Any) -> None:
            """Initialise the jupyverse kernel with a KernelProtocol."""
            super().__init__()
            self._protocol = KernelProtocol(shell, key=self.key, kernel_thread=kernel_thread)
            self._kernel_thread = kernel_thread
            self._tg: anyio.abc.TaskGroup | None = None

        async def start(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            """Start channel dispatch loops and signal task_status when ready."""
            async with anyio.create_task_group() as tg:
                self._tg = tg
                tg.start_soon(self._dispatch, self._to_shell_receive_stream, self._from_shell_send_stream)
                tg.start_soon(self._dispatch, self._to_control_receive_stream, self._from_control_send_stream)
                tg.start_soon(self._forward_iopub)
                tg.start_soon(self._forward_stdin_requests)
                tg.start_soon(self._forward_stdin_replies)
                self.started.set()
                task_status.started()
                await anyio.sleep_forever()

        async def stop(self) -> None:
            """Cancel the task group to stop all dispatch loops."""
            if self._tg:
                self._tg.cancel_scope.cancel()

        async def interrupt(self) -> None:
            """Interrupt the running cell on the kernel thread."""
            if self._kernel_thread is not None:
                self._kernel_thread.interrupt()

        async def _dispatch(
            self,
            recv_stream: MemoryObjectReceiveStream,
            send_stream: MemoryObjectSendStream,
        ) -> None:
            async for raw_msg in recv_stream:
                reply = await self._protocol.handle_message("shell", raw_msg)
                if reply is not None:
                    await send_stream.send(reply)

        async def _forward_iopub(self) -> None:
            async for raw_msg in self._protocol.iopub_receive:
                await self._from_iopub_send_stream.send(raw_msg)

        async def _forward_stdin_requests(self) -> None:
            async for raw_msg in self._protocol.stdin_receive:
                await self._from_stdin_send_stream.send(raw_msg)

        async def _forward_stdin_replies(self) -> None:
            async for raw_msg in self._to_stdin_receive_stream:
                _, parts = feed_identities(raw_msg)
                msg = deserialize_message(parts)
                if msg["msg_type"] == "input_reply":
                    self._protocol.supply_stdin_reply(msg["content"].get("value", ""))

    return _JupyQtJupyverseKernel


def create_kernel_factory(
    shell: InteractiveShell,
    kernel_thread: KernelThread | None = None,
) -> Any:
    """Create a KernelFactory for registering with jupyverse."""
    kernel_class = create_jupyqt_kernel_class(shell, kernel_thread)
    return KernelFactory(kernel_class)


if HAS_JUPYVERSE:
    from fps import Module

    class JupyQtKernelModule(Module):
        """FPS module providing DefaultKernelFactory for jupyverse.

        The shell and kernel_thread must be set via set_shell() before
        jupyverse starts (called by ServerLauncher._run()).
        This replaces fps_kernel_subprocess -- our kernel runs in-process.
        """

        _shell: InteractiveShell | None = None
        _kernel_thread: KernelThread | None = None

        @classmethod
        def set_shell(
            cls,
            shell: InteractiveShell,
            kernel_thread: KernelThread | None = None,
        ) -> None:
            """Store the shell and kernel_thread for use when jupyverse starts."""
            cls._shell = shell
            cls._kernel_thread = kernel_thread

        async def prepare(self) -> None:
            """Register a DefaultKernelFactory with the FPS dependency container."""
            if self._shell is None:
                raise RuntimeError("JupyQtKernelModule.set_shell() must be called before jupyverse starts")
            kernel_class = create_jupyqt_kernel_class(self._shell, self._kernel_thread)
            self.put(DefaultKernelFactory(kernel_class))
else:
    JupyQtKernelModule = None  # type: ignore[assignment,misc]
