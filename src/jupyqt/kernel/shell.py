"""InteractiveShell creation and output capture for jupyqt."""

from __future__ import annotations

import io
import sys
from typing import Callable

from IPython.core.interactiveshell import InteractiveShell


def create_shell() -> InteractiveShell:
    InteractiveShell.clear_instance()
    return InteractiveShell.instance(colors="neutral", autocall=0)


class OutputCapture:
    """Context manager that captures stdout/stderr and routes to callbacks."""

    def __init__(
        self,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ):
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr
        self._orig_stdout: io.TextIOBase | None = None
        self._orig_stderr: io.TextIOBase | None = None

    def __enter__(self):
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        if self._on_stdout:
            sys.stdout = _CallbackWriter(self._on_stdout)
        if self._on_stderr:
            sys.stderr = _CallbackWriter(self._on_stderr)
        return self

    def __exit__(self, *exc):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        return False


class _CallbackWriter(io.TextIOBase):
    """A writable stream that sends each write() to a callback."""

    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback

    def write(self, text: str) -> int:
        if text:
            self._callback(text)
        return len(text)

    def flush(self):
        pass
