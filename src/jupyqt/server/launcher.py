"""Manages jupyverse server lifecycle in a background thread."""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from IPython.core.interactiveshell import InteractiveShell

    from jupyqt.kernel.thread import KernelThread


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# Modules replaced by jupyqt's own implementations: the in-process kernel
# (jupyqt_kernel) supersedes kernel_subprocess, and JupyQtContentsModule
# supersedes contents. nbconvert is kept so JupyterLab's "Save and Export
# Notebook As" menu can list export formats (the old tornado/SSL import
# crash that forced its removal no longer occurs).
_EXCLUDED_MODULES = frozenset({
    "kernel_subprocess",
    "contents",
})


def _build_config(port: int) -> dict[str, Any]:
    """Build the fps config dict for jupyverse with our kernel and contents modules."""
    from importlib.metadata import entry_points  # noqa: PLC0415

    jupyverse_modules = {
        ep.name: {"type": ep.value}
        for ep in entry_points(group="jupyverse.modules")
        if ep.name not in _EXCLUDED_MODULES
    }
    jupyverse_modules["jupyqt_kernel"] = {
        "type": "jupyqt.server.plugin:JupyQtKernelModule",
    }
    jupyverse_modules["contents"] = {
        "type": "jupyqt.server.contents:JupyQtContentsModule",
    }
    jupyverse_modules["jupyqt_kernelspecs"] = {
        "type": "jupyqt.server.kernelspec:JupyQtKernelspecsModule",
    }
    jupyverse_modules["jupyqt_lab"] = {
        "type": "jupyqt.server.lab:JupyQtLabModule",
    }
    return {
        "jupyverse": {
            "type": "jupyverse_api.main:JupyverseModule",
            "config": {
                "host": "127.0.0.1",
                "port": port,
            },
            "modules": jupyverse_modules,
        },
    }


def _disable_zero_copy_send() -> None:
    """Make anycorn send file bodies through the stream instead of os.sendfile.

    On asyncio, anycorn's sendfile waits on EAGAIN with add_writer on a socket its
    transport owns, which raises and truncates the response (Lab chunks fail to load,
    seen on macOS). https://github.com/davidbrochart/anycorn/issues/95
    anycorn has no setting for this; with have_sendfile false it takes its TLS path,
    which reads the file and sends it through the stream. Zero-copy buys nothing
    for a localhost browser.
    """
    import anycorn.tcp_server  # noqa: PLC0415

    anycorn.tcp_server.have_sendfile = False


def _hand_shell_to_kernel_module(shell: InteractiveShell, kernel_thread: KernelThread | None) -> None:
    """Give the in-process kernel module the shell it runs cells in."""
    from jupyqt.server.plugin import JupyQtKernelModule  # noqa: PLC0415

    if JupyQtKernelModule is None:
        raise RuntimeError("jupyverse is required to run the JupyterLab server")
    JupyQtKernelModule.set_shell(shell, kernel_thread)


class ServerLauncher:
    """Starts and stops a jupyverse server in a background thread."""

    def __init__(
        self,
        shell: InteractiveShell,
        kernel_thread: KernelThread | None = None,
        port: int = 0,
        token: str | None = None,
        cwd: str | None = None,
    ) -> None:
        """Configure the server launcher with shell, optional kernel thread, port, and token."""
        self._shell = shell
        self._kernel_thread = kernel_thread
        self._port = port if port != 0 else _find_free_port()
        self._token = token or secrets.token_hex(16)
        self._cwd = cwd
        self._thread: threading.Thread | None = None
        self._root_module: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._error: BaseException | None = None

    @property
    def port(self) -> int:
        """The port on which the jupyverse server is listening."""
        return self._port

    @property
    def token(self) -> str:
        """The authentication token for the jupyverse server."""
        return self._token

    @property
    def url(self) -> str:
        """The full JupyterLab URL including the authentication token."""
        return f"http://localhost:{self._port}/lab?token={self._token}"

    @property
    def is_running(self) -> bool:
        """Whether the server thread is alive and started without error.

        JupyterLab's File > Shut Down exits the whole fps app, so a launcher can
        die without anyone calling stop(). Callers must check this before reusing
        one.
        """
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._error is None
        )

    def start(self) -> None:
        """Launch the server thread and block until the server is ready."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="jupyqt-server")
        self._thread.start()
        if not self._started.wait(timeout=60):
            raise TimeoutError("Server did not start within 60 seconds")
        if self._error is not None:
            raise RuntimeError("Server thread failed to start") from self._error

    def stop(self) -> None:
        """Signal the server to stop and join the server thread."""
        if self._root_module is not None and self._loop is not None:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._root_module._exit.set)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _run(self) -> None:
        """Start jupyverse via fps. Runs in the server thread."""
        prev_cwd = Path.cwd()
        try:
            if self._cwd is not None:
                os.chdir(self._cwd)

            _hand_shell_to_kernel_module(self._shell, self._kernel_thread)
            _disable_zero_copy_send()

            from jupyqt.server.kernelspec import remove_old_jupyqt_kernelspecs  # noqa: PLC0415

            remove_old_jupyqt_kernelspecs()

            import fps  # noqa: PLC0415

            config = _build_config(self._port)
            self._root_module = fps.get_root_module(config)
            # Increase timeouts — jupyverse has many modules to prepare
            self._root_module._prepare_timeout = 60
            self._root_module._start_timeout = 60

            # Run the module, signalling _started once the event loop is up
            import anyio  # noqa: PLC0415

            async def _main() -> None:
                self._loop = asyncio.get_running_loop()
                async with self._root_module:
                    self._started.set()
                    await self._root_module._exit.wait()

            anyio.run(_main)
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            self._started.set()
        finally:
            os.chdir(prev_cwd)
