# tests/test_thread.py
from __future__ import annotations

import threading

import pytest

from jupyqt.kernel.thread import KernelThread


@pytest.fixture
def kernel_thread(shell):
    kt = KernelThread(shell)
    yield kt
    if kt.is_alive():
        kt.stop()


def test_kernel_thread_starts_and_stops(kernel_thread):
    kernel_thread.start()
    assert kernel_thread.is_alive()
    kernel_thread.stop()
    assert not kernel_thread.is_alive()


def test_kernel_thread_runs_on_separate_thread(kernel_thread):
    kernel_thread.start()
    assert kernel_thread.thread_id != threading.main_thread().ident


def test_kernel_thread_has_event_loop(kernel_thread):
    kernel_thread.start()
    assert kernel_thread.loop is not None


def test_thread_safe_push(kernel_thread):
    kernel_thread.start()
    kernel_thread.push({"injected": 999})
    # Ensure push is processed by running a sync barrier on the kernel thread
    kernel_thread.run_sync(lambda: None)
    assert kernel_thread.shell.user_ns["injected"] == 999


def test_run_on_kernel_thread(kernel_thread):
    """Verify that run_sync executes code on the kernel thread."""
    kernel_thread.start()
    result = kernel_thread.run_sync(lambda: threading.current_thread().ident)
    assert result == kernel_thread.thread_id
