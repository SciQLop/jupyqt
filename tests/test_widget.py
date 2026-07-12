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

from PySide6.QtWebEngineCore import QWebEnginePage

from jupyqt.qt.widget import JupyterLabWidget, _LabPage


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
