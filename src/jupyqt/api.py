"""Public API for jupyqt — embed JupyterLab in PySide6 applications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyqt.kernel.shell import create_shell
from jupyqt.kernel.thread import KernelThread
from jupyqt.qt.proxy import MainThreadInvoker, QtProxy

if TYPE_CHECKING:
    from IPython.core.interactiveshell import InteractiveShell


class EmbeddedJupyter:
    """Batteries-included JupyterLab embedding for PySide6 apps.

    Usage::

        jupyter = EmbeddedJupyter()
        jupyter.shell.push({"my_data": data})
        jupyter.start()                      # starts kernel only
        layout.addWidget(jupyter.widget())    # starts server on first call
    """

    def __init__(self) -> None:
        """Create a new EmbeddedJupyter instance with a kernel and invoker."""
        self._shell = create_shell()
        self._kernel_thread = KernelThread(self._shell)
        self._invoker = MainThreadInvoker()
        self._launcher = None
        self._widget = None
        self._port = 0
        self._cwd: str | None = None
        self._started = False

    @property
    def shell(self) -> InteractiveShell:
        """The underlying IPython interactive shell."""
        return self._shell

    def push(self, variables: dict[str, Any]) -> None:
        """Thread-safe variable injection into the kernel namespace."""
        self._kernel_thread.push(variables)

    def wrap_qt(self, obj: Any) -> QtProxy:
        """Wrap a QObject so it can be safely accessed from the kernel thread."""
        return QtProxy(obj, self._invoker)

    def _ensure_server(self) -> None:
        """Start the jupyverse server if not already running."""
        if self._launcher is not None:
            return
        if not self._started:
            raise RuntimeError("Call start() before requesting widget or browser")
        from jupyqt.server.launcher import ServerLauncher  # noqa: PLC0415
        self._launcher = ServerLauncher(
            self._shell, self._kernel_thread, port=self._port, cwd=self._cwd,
        )
        self._launcher.start()
        if self._widget is not None:
            self._widget.load(self._launcher.url)

    def widget(self) -> Any:
        """Return the JupyterLab QWidget, starting the server if needed."""
        self._ensure_server()
        if self._widget is None:
            from jupyqt.qt.widget import JupyterLabWidget  # noqa: PLC0415
            self._widget = JupyterLabWidget()
        if self._launcher is not None:
            self._widget.load(self._launcher.url)
        return self._widget

    def open_in_browser(self) -> None:
        """Open the JupyterLab URL in the system default browser."""
        self._ensure_server()
        from PySide6.QtCore import QUrl  # noqa: PLC0415
        from PySide6.QtGui import QDesktopServices  # noqa: PLC0415
        QDesktopServices.openUrl(QUrl(self._launcher.url))

    def start(self, port: int = 0, cwd: str | None = None) -> None:
        """Start the kernel thread. The server starts lazily on first widget()/open_in_browser()."""
        self._port = port
        self._cwd = cwd
        self._kernel_thread.start()
        self._started = True

    def shutdown(self) -> None:
        """Stop the server and kernel thread, releasing resources."""
        if self._launcher is not None:
            self._launcher.stop()
            self._launcher = None
        self._kernel_thread.stop()
        self._started = False
