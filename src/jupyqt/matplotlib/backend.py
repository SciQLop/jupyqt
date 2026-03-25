"""Matplotlib Qt backend for jupyqt.

Renders figures using Agg on the kernel thread, then creates native Qt
figure windows on the main thread via MainThreadInvoker when show() is called.

Activate with::

    %matplotlib module://jupyqt.matplotlib.backend

Or from Python::

    import matplotlib
    matplotlib.use("module://jupyqt.matplotlib.backend")
"""

from __future__ import annotations

import contextlib
from typing import Any

from matplotlib._pylab_helpers import Gcf  # ty: ignore[unresolved-import]
from matplotlib.backend_bases import FigureManagerBase, _Backend  # ty: ignore[unresolved-import]
from matplotlib.backends.backend_agg import FigureCanvasAgg  # ty: ignore[unresolved-import]


class FigureCanvasJupyQT(FigureCanvasAgg):
    """Agg canvas that creates FigureManagerJupyQT instances."""

    # manager_class is set after FigureManagerJupyQT is defined below


_invoker: Any = None


def set_invoker(invoker: Any) -> None:
    """Set the MainThreadInvoker used to create Qt windows on the main thread."""
    global _invoker  # noqa: PLW0603
    _invoker = invoker


class FigureManagerJupyQT(FigureManagerBase):
    """Figure manager that creates Qt windows on demand via show()."""

    def __init__(self, canvas: FigureCanvasAgg, num: int | str) -> None:
        """Initialise with an Agg canvas and figure number."""
        super().__init__(canvas, num)
        self._window: Any = None
        self._qt_canvas: Any = None

    def show(self) -> None:
        """Create (or raise) a native Qt figure window on the main thread."""
        if _invoker is None:
            return
        figure = self.canvas.figure
        manager_num = self.num

        def _show() -> None:
            from matplotlib.backends.backend_qtagg import (  # noqa: PLC0415  # ty: ignore[unresolved-import]
                FigureCanvasQTAgg,
                NavigationToolbar2QT,
            )
            from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget  # noqa: PLC0415

            try:
                if self._window is not None and self._window.isVisible():
                    self._window.raise_()
                    self._window.activateWindow()
                    return
            except RuntimeError:
                pass
            self._window = None
            self._qt_canvas = None

            qt_canvas = FigureCanvasQTAgg(figure)
            toolbar = NavigationToolbar2QT(qt_canvas)

            central = QWidget()
            layout = QVBoxLayout(central)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(toolbar)
            layout.addWidget(qt_canvas)

            class _Window(QMainWindow):
                def closeEvent(self_, event: Any) -> None:  # noqa: N802, N805
                    Gcf.destroy(manager_num)
                    super().closeEvent(event)

            window = _Window()
            window.setCentralWidget(central)
            window.setWindowTitle(f"Figure {manager_num}")
            window.resize(
                int(figure.get_figwidth() * figure.dpi),
                int(figure.get_figheight() * figure.dpi) + toolbar.sizeHint().height(),
            )
            window.show()
            qt_canvas.draw()

            self._window = window
            self._qt_canvas = qt_canvas

        _invoker(_show)

    def destroy(self) -> None:
        """Close the Qt window if it exists."""
        if self._window is not None and _invoker is not None:
            with contextlib.suppress(RuntimeError):
                _invoker(self._window.close)
            self._window = None
            self._qt_canvas = None
        super().destroy()


FigureCanvasJupyQT.manager_class = FigureManagerJupyQT


@_Backend.export
class _BackendJupyQT(_Backend):
    FigureCanvas = FigureCanvasJupyQT
    FigureManager = FigureManagerJupyQT

    @staticmethod
    def mainloop() -> None:
        pass  # Qt event loop is already running in the main thread
