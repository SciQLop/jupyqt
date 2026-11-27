# tests/test_lab.py
"""Lab files must be sent by Starlette, never by anycorn's pathsend."""

from __future__ import annotations

import anyio

from jupyqt.server.lab import WithoutPathSend

PATHSEND = "http.response.pathsend"


def _scope_seen_by_app(scope: dict) -> dict:
    seen = {}

    async def app(scope, _receive, _send):
        seen.update(scope)

    anyio.run(WithoutPathSend(app), scope, None, None)
    return seen


def test_pathsend_is_hidden_from_the_app():
    scope = {"type": "http", "extensions": {PATHSEND: {}, "http.response.trailers": {}}}

    seen = _scope_seen_by_app(scope)

    assert seen["extensions"] == {"http.response.trailers": {}}
    assert PATHSEND in scope["extensions"]


def test_scope_without_extensions_passes_through():
    assert _scope_seen_by_app({"type": "lifespan"}) == {"type": "lifespan"}
