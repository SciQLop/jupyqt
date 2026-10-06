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
from PySide6.QtWebEngineCore import QWebEnginePage

from jupyqt.qt.widget import (
    BOOT_TIMEOUT_S,
    GIVE_UP_S,
    JupyterLabWidget,
    _LabPage,
    watchdog_action,
)


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
