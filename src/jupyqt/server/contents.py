"""Jupyverse Contents plugin that fills gaps in the upstream implementation.

Four upstream gaps are patched here:

1. `_Contents.write_content` writes the base64-encoded string to disk in the
   `format:"base64"` branch instead of decoding it first, so any binary file
   dropped into JupyterLab's file browser is saved as ASCII gibberish.

2. `_Contents.create_content` does not handle the standard Jupyter Contents
   API `{"copy_from": "<src>"}` request body, so copy-paste in the file
   browser raises a 500 ValidationError.

3. fps-contents does not expose `GET /files/{path:path}`, the raw-bytes
   download endpoint that JupyterLab's file browser builds via
   `Drive.getDownloadUrl` — so clicking "Download" produces a 404 and the
   QWebEngine save dialog writes an empty (or error-page) file.

4. `SaveContent` has no `chunk` field, so `_Contents.save_content` silently
   drops it while coercing the request body. JupyterLab's file browser splits
   any dropped file over 1MiB into a sequence of base64 PUTs tagged
   `chunk: 1, 2, ..., -1` (last) — without chunk awareness, each PUT
   overwrites the file instead of appending, leaving only the last chunk
   on disk.

This module provides a subclass that fixes all four, plus a jupyverse
Module that registers it in place of the default fps-contents ContentsModule.

It also runs the host application's notebook hooks (`NOTEBOOK_HOOKS`) when a
notebook is saved or opened, so the host can stamp or inspect notebook
metadata without a JupyterLab frontend extension.
"""

from __future__ import annotations

import base64
import json
import shutil
from typing import TYPE_CHECKING, Any, cast

import structlog
from anyio import CancelScope, Path, to_thread
from fastapi import APIRouter, Depends, HTTPException
from fps import Module
from fps_contents.routes import _Contents, get_available_path
from jupyverse_api import App
from jupyverse_auth import Auth, User
from jupyverse_contents import Contents
from jupyverse_contents.models import Content, SaveContent
from starlette.responses import FileResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger()


class NotebookHooks:
    """Host callbacks run in the server thread when a notebook is saved or opened.

    Save hooks take ``(absolute_path, notebook_dict)`` and return the notebook
    to write. Open hooks take the same arguments and return nothing. A hook
    that raises is logged and skipped: a broken hook must never lose a save.
    Hooks run on the server's event loop, so they must be quick.
    """

    def __init__(self) -> None:
        """Start with no hooks."""
        self._save_hooks: list[Callable[[str, dict], dict]] = []
        self._open_hooks: list[Callable[[str, dict], Any]] = []

    def add_save_hook(self, hook: Callable[[str, dict], dict]) -> None:
        """Run *hook* on every notebook save; its return value is what gets written."""
        self._save_hooks.append(hook)

    def add_open_hook(self, hook: Callable[[str, dict], Any]) -> None:
        """Run *hook* every time a notebook's content is read, i.e. opened."""
        self._open_hooks.append(hook)

    def clear(self) -> None:
        """Remove every hook."""
        self._save_hooks.clear()
        self._open_hooks.clear()

    def on_save(self, path: str, notebook: dict) -> dict:
        """Pass *notebook* through every save hook."""
        for hook in self._save_hooks:
            try:
                notebook = hook(path, notebook)
            except Exception:  # noqa: PERF203 -- one broken hook must not skip the others
                logger.exception("Notebook save hook failed", path=path)
        return notebook

    def on_open(self, path: str, notebook: dict | str) -> None:
        """Notify every open hook; *notebook* may still be serialized JSON."""
        if not self._open_hooks:
            return
        if isinstance(notebook, str):
            notebook = json.loads(notebook)
        for hook in self._open_hooks:
            try:
                hook(path, notebook)
            except Exception:  # noqa: PERF203 -- one broken hook must not skip the others
                logger.exception("Notebook open hook failed", path=path)


NOTEBOOK_HOOKS = NotebookHooks()


class _JupyQtContents(_Contents):
    """fps-contents _Contents with fixed base64 writes, copy-paste, and /files downloads."""

    def __init__(self, app: App, auth: Auth) -> None:
        """Register the extra GET /files/{path} route on top of the base router."""
        super().__init__(app, auth)
        files_router = APIRouter()
        read_user = auth.current_user(permissions={"contents": ["read"]})

        # Use the default-value Depends form: the Annotated form is not
        # recognized as a dependency by the jupyverse-pinned FastAPI, so the
        # user param falls through to a required query parameter and the
        # endpoint returns 422 before the handler is ever called.
        @files_router.get("/files/{path:path}")
        async def download_file(
            path: str,
            user: User = Depends(read_user),  # noqa: ARG001, B008, FAST002
        ) -> FileResponse:
            return await self._serve_file(path)

        self.include_router(files_router)

    async def _serve_file(self, path: str) -> FileResponse:
        rel = path.lstrip("/")
        p = Path(rel)
        if not await p.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(str(p), filename=p.name)

    async def create_content(
        self,
        path: str | None,
        request: Request,
        user: User,
    ) -> Content:
        """Intercept {'copy_from': ...} bodies and delegate to _copy_content."""
        body = await request.json()
        if "copy_from" in body:
            return await self._copy_content(path, body["copy_from"])
        return await super().create_content(path, request, user)

    async def get_content(
        self,
        path: str,
        content: int,
        user: User | None = None,
    ) -> Content:
        """Read content, running the notebook open hooks when a notebook is opened."""
        model = await super().get_content(path, content, user)
        if content and model.type == "notebook":
            absolute = str(await Path(path.lstrip("/")).absolute())
            NOTEBOOK_HOOKS.on_open(absolute, cast("dict | str", model.content))
        return model

    async def save_content(
        self,
        path: str | None,  # noqa: ARG002
        request: Request,
        response: Response,  # noqa: ARG002
        user: User,  # noqa: ARG002
    ) -> Content:
        """Pass the raw body to write_content so chunked uploads keep their `chunk` field."""
        body = await request.json()
        try:
            await self.write_content(body)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Error saving {body.get('path')}") from exc
        return await self.read_content(body["path"], get_content=False)

    async def _copy_content(self, dest_dir: str | None, src: str) -> Content:
        # FastAPI's {path:path} passes "/" for /api/contents/ and "sub" for
        # /api/contents/sub. Strip the leading slash so we stay relative to cwd.
        rel_dir = (dest_dir or "").lstrip("/")
        dest_parent = Path(rel_dir) if rel_dir else Path(".")
        src_path = Path(src.lstrip("/"))
        target = await get_available_path(
            dest_parent / src_path.name, sep="-Copy",
        )
        await to_thread.run_sync(shutil.copyfile, str(src_path), str(target))
        return await self.read_content(target, get_content=False)

    async def write_content(self, content: SaveContent | dict) -> None:
        """Write content to disk, decoding base64 payloads and assembling chunked uploads.

        JupyterLab tags chunked-upload PUTs with `chunk: 1, 2, ..., -1` (last);
        the first chunk (or a non-chunked upload, where `chunk` is absent)
        truncates the file, later chunks append.
        """
        chunk = content.get("chunk") if isinstance(content, dict) else None
        with CancelScope(shield=True):
            if not isinstance(content, SaveContent):
                content = SaveContent(**content)
            async with self.file_lock(content.path):
                if content.format == "base64":
                    content.content = cast("str", content.content)
                    data = base64.b64decode(content.content)
                    if chunk in (None, 1):
                        await Path(content.path).write_bytes(data)
                    else:
                        async with await Path(content.path).open("ab") as f:
                            await f.write(data)
                    return
                if content.format == "json":
                    dict_content = cast("dict", content.content)
                    if content.type == "notebook" and (
                        "metadata" in dict_content
                        and "orig_nbformat" in dict_content["metadata"]
                    ):
                        del dict_content["metadata"]["orig_nbformat"]
                    if content.type == "notebook":
                        absolute = str(await Path(content.path).absolute())
                        dict_content = NOTEBOOK_HOOKS.on_save(absolute, dict_content)
                    try:
                        str_content = json.dumps(dict_content, indent=2)
                    except TypeError as exc:
                        logger.warning(
                            "Error saving file", path=content.path, exc_info=exc,
                        )
                    else:
                        await Path(content.path).write_text(str_content)
                    return
                content.content = cast("str", content.content)
                await Path(content.path).write_text(content.content)


class JupyQtContentsModule(Module):
    """Registers _JupyQtContents in place of fps-contents' default."""

    async def prepare(self) -> None:
        """Instantiate the plugin and publish it as the Contents provider."""
        app = await self.get(App)
        auth = await self.get(Auth)
        contents = _JupyQtContents(app, auth)
        self.put(contents, Contents)
