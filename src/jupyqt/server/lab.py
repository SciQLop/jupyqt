"""Jupyverse module that lets the host application drive the embedded JupyterLab.

JupyterLab publishes its app object as ``window.jupyterapp`` only when the
``exposeAppInBrowser`` page option is true; jupyverse hardcodes it to false.
With the app exposed, the host can run Lab commands in the page, e.g. open a
file with ``docmanager:open`` instead of reloading Lab on ``/lab/tree/<path>``.
"""

from __future__ import annotations

from typing import Any

from fps import Module
from jupyverse_lab import PageConfig


async def expose_app_in_browser(config: dict[str, Any]) -> None:
    """PageConfig hook: make Lab publish itself as ``window.jupyterapp``."""
    config["exposeAppInBrowser"] = True


class JupyQtLabModule(Module):
    """Registers :func:`expose_app_in_browser` on jupyverse's page config."""

    async def prepare(self) -> None:
        """Hook into the page config every Lab page is rendered with."""
        page_config = await self.get(PageConfig)
        page_config.register(expose_app_in_browser)
