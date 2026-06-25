# tests/test_widget.py
"""The embedded page must grant ``window.open()`` a real target window.

JupyterLab's *Save and Export Notebook As* opens a blank window and navigates it
to the nbconvert download URL. The base ``QWebEnginePage.createWindow`` returns
None, so that export silently does nothing — the page subclass must override it.

Structural check only: importing the class needs no QApplication / Chromium, so
it is safe under the ``offscreen`` CI platform.
"""
from __future__ import annotations

from PySide6.QtWebEngineCore import QWebEnginePage

from jupyqt.qt.widget import _LabPage


def test_lab_page_overrides_create_window():
    assert _LabPage.createWindow is not QWebEnginePage.createWindow
