"""Jupyverse module that lets the host application drive the embedded JupyterLab.

JupyterLab publishes its app object as ``window.jupyterapp`` only when the
``exposeAppInBrowser`` page option is true; jupyverse hardcodes it to false.
With the app exposed, the host can run Lab commands in the page, e.g. open a
file with ``docmanager:open`` instead of reloading Lab on ``/lab/tree/<path>``.

The module also keeps anycorn from sending files itself (see :class:`WithoutPathSend`).
"""

from __future__ import annotations

from typing import Any

from fps import Module
from jupyverse_api.app import App
from jupyverse_lab import PageConfig

_PATHSEND = "http.response.pathsend"


async def expose_app_in_browser(config: dict[str, Any]) -> None:
    """PageConfig hook: make Lab publish itself as ``window.jupyterapp``."""
    config["exposeAppInBrowser"] = True


class WithoutPathSend:
    """ASGI middleware that hides the pathsend extension, so Starlette streams files itself.

    With pathsend, anycorn sends the file, and cuts it short in two ways:
    - on asyncio, os.sendfile hitting EAGAIN raises (Lab's JS chunks fail to load on
      macOS), https://github.com/davidbrochart/anycorn/issues/95
    - on Windows, it opens the file in text mode, so a 0x1A byte ends it.
    """

    def __init__(self, app: Any) -> None:
        """Wrap the ASGI *app*."""
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Call the app with a scope that no longer offers pathsend."""
        extensions = scope.get("extensions") or {}
        if _PATHSEND in extensions:
            scope = {**scope, "extensions": {k: v for k, v in extensions.items() if k != _PATHSEND}}
        await self.app(scope, receive, send)


class JupyQtLabModule(Module):
    """Exposes Lab to the host page and keeps anycorn from sending files itself."""

    async def prepare(self) -> None:
        """Hook into the page config every Lab page is rendered with, and wrap the app."""
        page_config = await self.get(PageConfig)
        page_config.register(expose_app_in_browser)
        app = await self.get(App)
        app.add_middleware(WithoutPathSend)
