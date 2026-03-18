"""Background thread for the IPython kernel.

The kernel thread owns the InteractiveShell after start(). It runs an asyncio
event loop for message dispatch and provides thread-safe access methods.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable, TypeVar

from IPython.core.interactiveshell import InteractiveShell

T = TypeVar("T")


class KernelThread:
    """Background thread with its own asyncio loop for kernel execution."""

    def __init__(self, shell: InteractiveShell) -> None:
        self._shell = shell
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._thread_id: int | None = None

    @property
    def shell(self) -> InteractiveShell:
        return self._shell

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def thread_id(self) -> int | None:
        return self._thread_id

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="jupyqt-kernel")
        self._thread.start()
        self._started.wait(timeout=10)

    def stop(self) -> None:
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

        def _wrapper():
            try:
                future.set_result(func(*args))
            except Exception as e:
                future.set_exception(e)

        self._loop.call_soon_threadsafe(_wrapper)
        return future.result(timeout=30)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._thread_id = threading.current_thread().ident
        self._started.set()
        self._loop.run_forever()
