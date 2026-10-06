"""JupyterLab widget embedding via QWebEngineView."""

from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QLabel, QStackedWidget, QWidget

log = logging.getLogger(__name__)

WATCHDOG_INTERVAL_MS = 1000
# Lab boots in ~2 s on an idle machine; the first start after an update is far
# busier, so leave a slow boot room before calling it stuck.
BOOT_TIMEOUT_S = 15.0
GIVE_UP_S = 120.0
_LAB_BOOTED_JS = "!!document.querySelector('.jp-LabShell')"


def watchdog_action(*, booted: bool, load_failed: bool, attempt_age: float, total_age: float) -> str:
    """What the boot watchdog does next: ``stop``, ``give_up``, ``reload`` or ``wait``."""
    if booted:
        return "stop"
    if total_age > GIVE_UP_S:
        return "give_up"
    if load_failed or attempt_age > BOOT_TIMEOUT_S:
        return "reload"
    return "wait"


class _PopupPage(QWebEnginePage):
    """Transient page backing a ``window.open()`` target.

    JupyterLab's *Save and Export Notebook As* opens a blank window and then
    navigates it to the nbconvert download URL. Giving that window a real page on
    the shared profile lets the navigation proceed, so the attachment response
    fires ``downloadRequested`` (handled by :class:`JupyterLabWidget`). The page
    disposes of itself once the navigation resolves.
    """

    def __init__(self, profile: QWebEngineProfile, parent: QWebEnginePage) -> None:
        """Create a transient page that self-destructs when its load finishes."""
        super().__init__(profile, parent)
        self.loadFinished.connect(lambda _ok: self.deleteLater())


class _LabPage(QWebEnginePage):
    """Main page that grants ``window.open()`` a real target window.

    The base ``QWebEnginePage.createWindow`` returns None, which makes JavaScript
    ``window.open`` evaluate to null — JupyterLab's notebook export then silently
    does nothing.
    """

    def createWindow(self, _type: QWebEnginePage.WebWindowType) -> QWebEnginePage:  # noqa: N802
        """Return a transient page so ``window.open()`` navigations proceed."""
        return _PopupPage(self.profile(), self)


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

        self._web_view = QWebEngineView(self)
        self._web_view.setPage(_LabPage(self._web_view))
        self._web_view.loadFinished.connect(self._on_load_finished)
        QWebEngineProfile.defaultProfile().downloadRequested.connect(
            self._on_download_requested,
        )
        self.addWidget(self._web_view)

        self.setCurrentWidget(self._placeholder)

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check_lab_booted)
        self._first_load_at = 0.0
        self._attempt_at = 0.0
        self._load_failed = False

    def load(self, url: str) -> None:
        """Navigate the embedded browser to the given URL.

        A watchdog then checks every second that JupyterLab booted, and loads the
        URL again when the page failed to load or stayed blank (see
        :func:`watchdog_action`).
        """
        self._url = url
        self._first_load_at = time.monotonic()
        self._navigate(url)
        self._watchdog.start()

    def _navigate(self, url: str) -> None:
        self._attempt_at = time.monotonic()
        self._load_failed = False
        self._web_view.load(QUrl(url))

    def _left_lab(self, lab_url: str) -> bool:
        """Lab's File > Log Out navigates away on purpose; never drag it back."""
        current = self._web_view.url().toString()
        return not self._load_failed and bool(current) and not current.startswith(lab_url.partition("?")[0])

    def _check_lab_booted(self) -> None:
        if self._url is None or self._left_lab(self._url):
            self._watchdog.stop()
            return
        self._web_view.page().runJavaScript(_LAB_BOOTED_JS, 0, self._on_boot_probe)

    def _on_boot_probe(self, booted: object) -> None:
        if self._url is None or not self._watchdog.isActive():
            return
        now = time.monotonic()
        action = watchdog_action(
            booted=bool(booted),
            load_failed=self._load_failed,
            attempt_age=now - self._attempt_at,
            total_age=now - self._first_load_at,
        )
        if action in {"stop", "give_up"}:
            self._watchdog.stop()
        if action == "give_up":
            log.warning("JupyterLab did not start after %.0f s, giving up on reloading it", GIVE_UP_S)
        if action == "reload":
            log.info("JupyterLab did not start, loading it again")
            self._navigate(self._url)

    def is_on(self, url_prefix: str) -> bool:
        """Whether the page currently shown starts with url_prefix.

        Reports where the view actually *is*, not where it was last sent: Lab's
        File > Log Out navigates it to /logout on its own, and only the committed
        URL reveals that.
        """
        return self._web_view.url().toString().startswith(url_prefix)

    def open_in_browser(self) -> None:
        """Open the current URL in the system default browser."""
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    @staticmethod
    def _on_download_requested(download: Any) -> None:
        suggested = download.downloadDirectory() + "/" + download.downloadFileName()
        path, _ = QFileDialog.getSaveFileName(
            None,
            "Save File",
            suggested,
            "All Files (*)",
        )
        if path:
            download.setDownloadDirectory(path.rsplit("/", 1)[0])
            download.setDownloadFileName(path.rsplit("/", 1)[1])
            download.accept()
        else:
            download.cancel()

    def _on_load_finished(self, ok: bool) -> None:  # noqa: FBT001
        self._load_failed = not ok
        if ok:
            self.setCurrentWidget(self._web_view)
            self.ready.emit()
