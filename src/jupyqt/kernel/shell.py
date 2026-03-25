"""InteractiveShell creation and output capture for jupyqt."""

from __future__ import annotations

import base64
import io
import sys
from typing import TYPE_CHECKING, Any

from IPython.core.interactiveshell import InteractiveShell

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Self


class _JupyQTShell(InteractiveShell):
    """InteractiveShell subclass with enable_gui no-op (Qt loop already runs)."""

    def enable_gui(self, gui: str | None = None) -> None:
        pass


def create_shell() -> _JupyQTShell:
    """Create and return a fresh IPython InteractiveShell instance."""
    _JupyQTShell.clear_instance()
    shell = _JupyQTShell.instance(colors="neutral", autocall=0)
    _activate_matplotlib_inline(shell)
    return shell


def _activate_matplotlib_inline(shell: InteractiveShell) -> None:
    """Activate the matplotlib inline backend if matplotlib is available.

    Replaces matplotlib_inline's flush_figures hook with a backend-aware
    version so switching to a different backend (e.g. the jupyqt Qt backend)
    stops the hook from closing figures and rendering them inline.
    """
    try:
        import matplotlib as mpl  # noqa: PLC0415  # ty: ignore[unresolved-import]

        mpl.use("module://matplotlib_inline.backend_inline")
        from matplotlib_inline.backend_inline import configure_inline_support, flush_figures  # noqa: PLC0415
        configure_inline_support(shell, backend="inline")

        def _flush_if_inline() -> None:
            if "inline" in mpl.get_backend().lower():
                flush_figures()

        shell.events.unregister("post_execute", flush_figures)
        shell.events.register("post_execute", _flush_if_inline)
    except (ImportError, ModuleNotFoundError):
        pass


def encode_display_data(format_dict: dict[str, Any]) -> dict[str, Any]:
    """Base64-encode bytes values for the Jupyter wire protocol."""
    return {
        mime: base64.b64encode(value).decode("ascii") if isinstance(value, bytes) else value
        for mime, value in format_dict.items()
    }


class DisplayCapture:
    """Context manager intercepting shell.display_pub.publish calls."""

    def __init__(self, shell: InteractiveShell) -> None:
        """Attach to the given shell's display publisher."""
        self._shell = shell
        self._original_publish: Any = None
        self.outputs: list[dict[str, Any]] = []

    def _capture(
        self,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        source: str | None = None,  # noqa: ARG002
        *,
        transient: dict[str, Any] | None = None,
        update: bool = False,  # noqa: ARG002
    ) -> None:
        self.outputs.append({
            "data": encode_display_data(data),
            "metadata": metadata or {},
            "transient": transient or {},
        })

    def __enter__(self) -> Self:
        self._original_publish = self._shell.display_pub.publish
        self._shell.display_pub.publish = self._capture
        return self

    def __exit__(self, *exc: object) -> bool:
        self._shell.display_pub.publish = self._original_publish
        return False


class OutputCapture:
    """Context manager that captures stdout/stderr and routes to callbacks."""

    def __init__(
        self,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ) -> None:
        """Configure callbacks for captured stdout and stderr output."""
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr
        self._orig_stdout: io.TextIOBase | None = None
        self._orig_stderr: io.TextIOBase | None = None

    def __enter__(self) -> Self:
        self._orig_stdout = sys.stdout  # ty: ignore[invalid-assignment]
        self._orig_stderr = sys.stderr  # ty: ignore[invalid-assignment]
        if self._on_stdout:
            sys.stdout = _CallbackWriter(self._on_stdout)
        if self._on_stderr:
            sys.stderr = _CallbackWriter(self._on_stderr)
        return self

    def __exit__(self, *exc: object) -> bool:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        return False

    def flush(self) -> None:
        """No-op flush to satisfy the stream interface."""


class _CallbackWriter(io.TextIOBase):
    """A writable stream that sends each write() to a callback."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        """Attach the given callback as the write target."""
        self._callback = callback

    def write(self, text: str) -> int:
        """Forward non-empty text to the callback and return its length."""
        if text:
            self._callback(text)
        return len(text)

    def flush(self) -> None:
        """No-op flush to satisfy the stream interface."""
