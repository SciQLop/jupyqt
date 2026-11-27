# tests/test_widget.py
"""The embedded page must grant ``window.open()`` a real target window.

JupyterLab's *Save and Export Notebook As* opens a blank window and navigates it
to the nbconvert download URL. The base ``QWebEnginePage.createWindow`` returns
None, so that export silently does nothing — the page subclass must override it.

Structural check only: importing the class needs no QApplication / Chromium, so
it is safe under the ``offscreen`` CI platform.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import SIGNAL
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from jupyqt.qt.widget import (
    BOOT_TIMEOUT_S,
    CRASH_WINDOW_S,
    GIVE_UP_S,
    MAX_CRASHES,
    JupyterLabWidget,
    _LabPage,
    enable_embedded_pdf,
    recent_crashes,
    watchdog_action,
)

Status = QWebEnginePage.RenderProcessTerminationStatus
LAB = "http://127.0.0.1:1/lab?token=t"


@pytest.mark.parametrize(
    ("booted", "load_failed", "attempt_age", "total_age", "expected"),
    [
        (True, False, 1.0, 1.0, "stop"),
        (False, False, 1.0, 1.0, "wait"),
        (False, True, 1.0, 1.0, "reload"),
        (False, False, BOOT_TIMEOUT_S + 1, BOOT_TIMEOUT_S + 1, "reload"),
        (False, True, 1.0, GIVE_UP_S + 1, "give_up"),
        (True, False, 1.0, GIVE_UP_S + 1, "stop"),
    ],
)
def test_watchdog_action(booted, load_failed, attempt_age, total_age, expected):
    """A page that fails to load is retried at once; one that loaded but never
    booted Lab (the white page) is reloaded after BOOT_TIMEOUT_S; retrying stops
    once Lab is up or after GIVE_UP_S."""
    assert (
        watchdog_action(
            booted=booted,
            load_failed=load_failed,
            attempt_age=attempt_age,
            total_age=total_age,
        )
        == expected
    )


def test_lab_page_overrides_create_window():
    assert _LabPage.createWindow is not QWebEnginePage.createWindow


def test_download_requested_cancels_on_dialog_cancel():
    """Cancelling the save-file dialog must cancel the download, not abandon it."""
    download = MagicMock()
    download.downloadDirectory.return_value = "/home/user/Downloads"
    download.downloadFileName.return_value = "notebook.pdf"

    with patch("jupyqt.qt.widget.QFileDialog.getSaveFileName", return_value=("", "")):
        JupyterLabWidget._on_download_requested(download)

    download.cancel.assert_called_once()
    download.accept.assert_not_called()


def test_lab_pages_enable_the_pdf_viewer_plugin():
    """Lab shows a PDF in ``<object type="application/pdf">``; QtWebEngine leaves it
    blank unless Pepper plugins are on, even though ``PdfViewerEnabled`` is."""
    settings = MagicMock()

    enable_embedded_pdf(settings)

    settings.setAttribute.assert_called_once_with(QWebEngineSettings.WebAttribute.PluginsEnabled, True)  # noqa: FBT003 -- Qt API


@pytest.fixture
def lab_widget(qtbot):
    """A widget that believes it shows LAB, with load() recorded instead of run."""
    widget = JupyterLabWidget()
    qtbot.addWidget(widget)
    widget._url = LAB
    widget.load = MagicMock()
    return widget


def _kill_renderer(widget, status=Status.CrashedTerminationStatus):
    # Called directly: PySide6 6.8 can't emit this signal from Python (its enum
    # isn't a registered meta type); the C++ emission works there.
    widget._on_render_process_terminated(status, 11)


def _crash_receivers(page) -> int:
    return page.receivers(SIGNAL("renderProcessTerminated(QWebEnginePage::RenderProcessTerminationStatus,int)"))


def test_lab_page_reports_renderer_crashes_to_the_widget(lab_widget):
    plain = QWebEngineView()

    assert _crash_receivers(lab_widget._web_view.page()) == _crash_receivers(plain.page()) + 1


def test_crashed_renderer_reloads_lab(lab_widget):
    """Without --single-process a renderer crash only kills the page; Lab must come back."""
    _kill_renderer(lab_widget)

    lab_widget.load.assert_called_once_with(LAB)


def test_normal_renderer_exit_does_not_reload(lab_widget):
    _kill_renderer(lab_widget, Status.NormalTerminationStatus)

    lab_widget.load.assert_not_called()


def test_crash_loop_gives_up(lab_widget):
    for _ in range(MAX_CRASHES + 2):
        _kill_renderer(lab_widget)

    assert lab_widget.load.call_count == MAX_CRASHES


def test_old_crashes_are_forgotten():
    now = 1000.0
    assert recent_crashes([now - CRASH_WINDOW_S - 1, now - 1], now) == [now - 1]
