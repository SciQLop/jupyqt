from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from jupyqt.qt.proxy import MainThreadInvoker, QtProxy


class FakeWidget(QObject):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._title = "initial"
        self.seen_arg = None

    def title(self) -> str:
        return self._title

    def set_title(self, value: str) -> None:
        self._title = value

    def get_thread_name(self) -> str:
        return threading.current_thread().name

    def take(self, other) -> str:
        self.seen_arg = other
        return type(other).__name__


def _run_in_worker(qtbot, fn):
    """Run fn on a worker thread and return its result once the thread is done."""
    box: dict = {}

    def worker():
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=worker, name="test-worker")
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()
    assert "error" not in box, box["error"]
    return box["result"]


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


def test_proxy_wraps_qobjects_inside_returned_containers(qtbot):
    """A QObject inside a returned list must not escape unwrapped."""
    parent = FakeWidget()
    child = FakeWidget()
    child.setParent(parent)

    proxy = QtProxy(parent, MainThreadInvoker())

    def list_children():
        return proxy.children()

    children = _run_in_worker(qtbot, list_children)

    def call_first_child():
        return children[0].get_thread_name()

    assert all(isinstance(c, QtProxy) for c in children)
    assert _run_in_worker(qtbot, call_first_child) == threading.main_thread().name


def test_proxy_keeps_signals_connectable(qtbot):
    """Signals are callable, so they must not be turned into a plain function."""
    widget = FakeWidget()
    proxy = QtProxy(widget, MainThreadInvoker())
    seen = []

    _run_in_worker(qtbot, lambda: proxy.changed.connect(seen.append))
    widget.changed.emit("hello")
    qtbot.waitUntil(lambda: seen == ["hello"], timeout=5000)


def test_proxy_marshals_attribute_assignment(qtbot):
    """`proxy.attr = value` must reach the target, not stick to the proxy."""
    widget = FakeWidget()
    proxy = QtProxy(widget, MainThreadInvoker())

    def assign():
        proxy.late_attribute = 42

    _run_in_worker(qtbot, assign)

    assert getattr(widget, "late_attribute") == 42  # noqa: B009 — set through the proxy


def test_proxy_unwraps_proxied_arguments(qtbot):
    """A proxy passed back into a Qt call must arrive as the real object."""
    receiver = FakeWidget()
    other = FakeWidget()
    receiver_proxy = QtProxy(receiver, MainThreadInvoker())
    other_proxy = QtProxy(other, MainThreadInvoker())

    type_name = _run_in_worker(qtbot, lambda: receiver_proxy.take(other_proxy))

    assert type_name == "FakeWidget"
    assert receiver.seen_arg is other
