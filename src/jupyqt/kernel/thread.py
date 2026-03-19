"""Background thread for the IPython kernel.

The kernel thread owns the InteractiveShell after start(). It runs an asyncio
event loop for message dispatch and provides thread-safe access methods.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import ctypes
import threading
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from IPython.core.interactiveshell import InteractiveShell

T = TypeVar("T")


class KernelThread:
    """Background thread with its own asyncio loop for kernel execution."""

    def __init__(self, shell: InteractiveShell) -> None:
        """Bind the kernel thread to the given IPython shell."""
        self._shell = shell
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._thread_id: int | None = None

    @property
    def shell(self) -> InteractiveShell:
        """The IPython shell running on this thread."""
        return self._shell

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The asyncio event loop owned by this thread, or None if not started."""
        return self._loop

    @property
    def thread_id(self) -> int | None:
        """OS thread identifier, or None if the thread has not started."""
        return self._thread_id

    def is_alive(self) -> bool:
        """Return True if the kernel thread is currently running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the kernel thread and block until its event loop is ready."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="jupyqt-kernel")
        self._thread.start()
        self._started.wait(timeout=10)

    def stop(self) -> None:
        """Stop the kernel thread's event loop and join the thread."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
            self._loop = None
            self._thread_id = None

    def push(self, variables: dict[str, Any]) -> None:
        """Thread-safe variable injection into the shell namespace."""
        if self._loop is None:
            self._shell.push(variables)
        else:
            self._loop.call_soon_threadsafe(self._shell.push, variables)

    def run_sync(self, func: Callable[..., T], *args: Any) -> T:
        """Run a synchronous callable on the kernel thread, blocking until done."""
        if self._loop is None:
            raise RuntimeError("KernelThread is not running")
        future: concurrent.futures.Future[T] = concurrent.futures.Future()

        def _wrapper() -> None:
            try:
                future.set_result(func(*args))
            except Exception as e:  # noqa: BLE001
                future.set_exception(e)

        self._loop.call_soon_threadsafe(_wrapper)
        return future.result(timeout=30)

    def run_coroutine(self, coro: Awaitable[T]) -> T:
        """Schedule a coroutine on the kernel thread's loop, blocking until done."""
        if self._loop is None:
            raise RuntimeError("KernelThread is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def interrupt(self) -> None:
        """Raise KeyboardInterrupt in the kernel thread to stop running code."""
        tid = self._thread_id
        if tid is None:
            return
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid), ctypes.py_object(KeyboardInterrupt),
        )

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._thread_id = threading.current_thread().ident
        self._started.set()
        self._loop.run_forever()
