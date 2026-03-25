"""JupyterLab widget embedding via QWebEngineView."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget


class JupyterLabWidget(QStackedWidget):
    """QWidget that embeds JupyterLab via QWebEngineView."""

    ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the widget with a loading placeholder and a QWebEngineView."""
        super().__init__(parent)
        self._url: str | None = None

        self._placeholder = QLabel("Loading JupyterLab...")
        self._placeholder.setAlignment(Qt.AlignCenter)  # ty: ignore[unresolved-attribute]
        self.addWidget(self._placeholder)

        self._profile = QWebEngineProfile("jupyqt", self)
        page = QWebEnginePage(self._profile, self)
        self._web_view = QWebEngineView(self)
        self._web_view.setPage(page)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self.addWidget(self._web_view)

        self.setCurrentWidget(self._placeholder)

    def load(self, url: str) -> None:
        """Navigate the embedded browser to the given URL."""
        self._url = url
        self._web_view.load(QUrl(url))

    def open_in_browser(self) -> None:
        """Open the current URL in the system default browser."""
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def _on_load_finished(self, ok: bool) -> None:  # noqa: FBT001
        if ok:
            self.setCurrentWidget(self._web_view)
            self.ready.emit()
