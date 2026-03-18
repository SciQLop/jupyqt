from __future__ import annotations

import threading

from PySide6.QtCore import QObject

from jupyqt.qt.proxy import MainThreadInvoker, QtProxy


class FakeWidget(QObject):
    def __init__(self):
        super().__init__()
        self._title = "initial"

    def title(self) -> str:
        return self._title

    def set_title(self, value: str) -> None:
        self._title = value

    def get_thread_name(self) -> str:
        return threading.current_thread().name


def test_proxy_calls_execute_on_main_thread(qtbot):
    widget = FakeWidget()
    invoker = MainThreadInvoker()
    proxy = QtProxy(widget, invoker)

    result = [None]
    error = [None]

    def worker():
        try:
            result[0] = proxy.get_thread_name()
        except Exception as e:  # noqa: BLE001
            error[0] = e

    t = threading.Thread(target=worker, name="test-worker")
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()

    assert error[0] is None
    assert result[0] == threading.main_thread().name


def test_proxy_method_returns_value(qtbot):
    widget = FakeWidget()
    invoker = MainThreadInvoker()
    proxy = QtProxy(widget, invoker)

    result = [None]

    def worker():
        result[0] = proxy.title()

    t = threading.Thread(target=worker)
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()

    assert result[0] == "initial"


def test_proxy_wraps_qobject_returns(qtbot):
    parent = FakeWidget()
    child = FakeWidget()
    child.setParent(parent)

    invoker = MainThreadInvoker()
    proxy = QtProxy(parent, invoker)

    result = [None]

    def worker():
        children = proxy.children()
        result[0] = children

    t = threading.Thread(target=worker)
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()

    assert isinstance(result[0], list)
