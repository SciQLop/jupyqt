# tests/test_integration.py
from __future__ import annotations

import pytest

from jupyqt.api import EmbeddedJupyter


@pytest.fixture
def jupyter():
    j = EmbeddedJupyter()
    yield j
    j.shutdown()
    from IPython.core.interactiveshell import InteractiveShell
    InteractiveShell.clear_instance()


def test_shell_accessible_before_start(jupyter):
    assert jupyter.shell is not None
    jupyter.shell.push({"test_var": 42})
    assert jupyter.shell.user_ns["test_var"] == 42


def test_wrap_qt(jupyter, qtbot):
    from PySide6.QtCore import QObject
    from jupyqt.qt.proxy import QtProxy

    obj = QObject()
    proxy = jupyter.wrap_qt(obj)
    assert isinstance(proxy, QtProxy)


def test_push_before_start(jupyter):
    jupyter.push({"x": 10})
    assert jupyter.shell.user_ns["x"] == 10
