"""jupyqt package.

Embed JupyterLab in PySide6 applications
"""

from __future__ import annotations

from jupyqt._internal.cli import get_parser, main

__all__: list[str] = ["get_parser", "main"]
