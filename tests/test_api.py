from __future__ import annotations

from jupyqt.api import EmbeddedJupyter


def test_kernel_thread_accessor_and_interrupt():
    ej = EmbeddedJupyter()
    # kernel_thread is the same object used internally, exposed read-only
    assert ej.kernel_thread is ej._kernel_thread
    # interrupt must not raise even before the thread is started (no-op)
    ej.interrupt()
