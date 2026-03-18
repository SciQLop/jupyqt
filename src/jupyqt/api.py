"""Public API for jupyqt — embed JupyterLab in PySide6 applications."""

from __future__ import annotations

from typing import Any

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.shell import create_shell
from jupyqt.kernel.thread import KernelThread
from jupyqt.qt.proxy import MainThreadInvoker, QtProxy


class EmbeddedJupyter:
    """Batteries-included JupyterLab embedding for PySide6 apps.

    Usage::

        jupyter = EmbeddedJupyter()
        jupyter.shell.push({"my_data": data})
        jupyter.start()
        layout.addWidget(jupyter.widget())
    """

    def __init__(self) -> None:
        self._shell = create_shell()
        self._kernel_thread = KernelThread(self._shell)
        self._invoker = MainThreadInvoker()
        self._launcher = None
        self._widget = None
        self._started = False

    @property
    def shell(self) -> InteractiveShell:
        return self._shell

    def push(self, variables: dict[str, Any]) -> None:
        """Thread-safe variable injection into the kernel namespace."""
        self._kernel_thread.push(variables)

    def wrap_qt(self, obj: Any) -> QtProxy:
        return QtProxy(obj, self._invoker)

    def widget(self):
        if self._widget is None:
            from jupyqt.qt.widget import JupyterLabWidget
            self._widget = JupyterLabWidget()
        if self._launcher is not None:
            self._widget.load(self._launcher.url)
        return self._widget

    def open_in_browser(self) -> None:
        if self._launcher is not None:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self._launcher.url))

    def start(self, port: int = 0) -> None:
        self._kernel_thread.start()
        from jupyqt.server.launcher import ServerLauncher
        self._launcher = ServerLauncher(self._shell, self._kernel_thread, port=port)
        self._launcher.start()
        self._started = True
        if self._widget is not None:
            self._widget.load(self._launcher.url)

    def shutdown(self) -> None:
        if self._launcher is not None:
            self._launcher.stop()
            self._launcher = None
        self._kernel_thread.stop()
        self._started = False
