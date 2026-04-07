"""Manages jupyverse server lifecycle in a background thread."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import socket
import sys
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


def _write_kernelspec(kernels_dir: Path, spec_text: str) -> bool:
    """Try to write kernel.json atomically. Return True on success."""
    kernel_json = kernels_dir / "kernel.json"
    if kernel_json.exists():
        return True
    try:
        kernels_dir.mkdir(parents=True, exist_ok=True)
        with open(kernel_json, "x", encoding="utf-8") as f:  # noqa: PTH123
            f.write(spec_text)
    except FileExistsError:
        pass
    except OSError:
        return False
    return True


def _ensure_kernelspec() -> None:
    """Write a minimal python3 kernel spec if one doesn't already exist.

    jupyqt doesn't use ipykernel, but JupyterLab's frontend needs a
    kernel spec to be discoverable via /api/kernelspecs.  Tries sys.prefix
    first, falls back to the user Jupyter data dir if that isn't writable.
    """
    spec = {
        "argv": [sys.executable, "-m", "jupyqt", "-f", "{connection_file}"],
        "display_name": "Python 3 (jupyqt)",
        "language": "python",
    }
    spec_text = json.dumps(spec, indent=1) + "\n"
    prefix_dir = Path(sys.prefix) / "share" / "jupyter" / "kernels" / "python3"
    if _write_kernelspec(prefix_dir, spec_text):
        return
    from jupyter_core.paths import jupyter_data_dir  # noqa: PLC0415

    user_dir = Path(jupyter_data_dir()) / "kernels" / "python3"
    if not _write_kernelspec(user_dir, spec_text):
        logging.getLogger(__name__).warning(
            "Could not write kernelspec to %s or %s — kernelspecs may be unavailable",
            prefix_dir / "kernel.json",
            user_dir / "kernel.json",
        )


_EXCLUDED_MODULES = frozenset({
    "kernel_subprocess",
    "nbconvert",
})


def _build_config(port: int) -> dict[str, Any]:
    """Build the fps config dict for jupyverse with our kernel module."""
    from importlib.metadata import entry_points  # noqa: PLC0415

    jupyverse_modules = {
        ep.name: {"type": ep.value}
        for ep in entry_points(group="jupyverse.modules")
        if ep.name not in _EXCLUDED_MODULES
    }
    jupyverse_modules["jupyqt_kernel"] = {
        "type": "jupyqt.server.plugin:JupyQtKernelModule",
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
            _ensure_kernelspec()

            from jupyqt.server.plugin import JupyQtKernelModule  # noqa: PLC0415

            JupyQtKernelModule.set_shell(self._shell, self._kernel_thread)  # ty: ignore[unresolved-attribute]

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
