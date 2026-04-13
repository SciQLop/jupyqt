"""Reproducer for upstream fps-contents base64 upload bug + verification of our fix.

Upstream fps-contents `_Contents.write_content` writes the literal base64
string to disk in the base64 branch instead of decoding it first. Dropping
any binary file into JupyterLab's file browser therefore produces an
ASCII-gibberish file. Our `_JupyQtContents` subclass fixes this.
"""
from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager

import anyio
import pytest
from fps_contents.routes import _Contents
from jupyverse_contents.models import SaveContent
from starlette.responses import FileResponse

from jupyqt.server.contents import _JupyQtContents


@asynccontextmanager
async def _noop_lock(_path: str):
    yield


class _FakeContents(_JupyQtContents):
    """_JupyQtContents with no-op file lock and no FastAPI router setup."""

    def __init__(self) -> None:
        pass

    def file_lock(self, path: str):
        return _noop_lock(path)


_BINARY = b"col_a,col_b\n1,2\nbinary:\x00\x01\xfe\xff"


def _make_payload() -> SaveContent:
    return SaveContent(
        name="sample.csv",
        path="sample.csv",
        type="file",
        format="base64",
        content=base64.b64encode(_BINARY).decode("ascii"),
    )


def test_upstream_fps_contents_writes_base64_string_verbatim(tmp_path, monkeypatch):
    """Documents the upstream bug: base64 branch writes the encoded string as-is."""
    monkeypatch.chdir(tmp_path)
    payload = _make_payload()

    anyio.run(_Contents.write_content, _FakeContents(), payload)

    on_disk = (tmp_path / "sample.csv").read_bytes()
    assert on_disk != _BINARY
    assert on_disk == payload.content.encode("ascii")


def test_jupyqt_contents_decodes_base64_and_writes_original_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    anyio.run(_JupyQtContents.write_content, _FakeContents(), _make_payload())

    assert (tmp_path / "sample.csv").read_bytes() == _BINARY


class _FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


def test_upstream_fps_contents_rejects_copy_from(tmp_path, monkeypatch):
    """Upstream CreateContent model has no copy_from field."""
    from jupyverse_contents.models import CreateContent
    from pydantic import ValidationError
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        CreateContent(copy_from="src.csv")


def test_jupyqt_contents_copy_from_copies_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "matplotlib_demo.ipynb"
    src.write_text(json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))
    req = _FakeRequest({"copy_from": "matplotlib_demo.ipynb"})

    result = anyio.run(
        _JupyQtContents.create_content, _FakeContents(), "", req, None,
    )

    copied = tmp_path / "matplotlib_demo.ipynb"
    # Source stays intact:
    assert copied.exists()
    # A copy gets an auto-named sibling because the original already exists:
    copies = sorted(p.name for p in tmp_path.iterdir())
    assert "matplotlib_demo-Copy1.ipynb" in copies
    assert result.path.endswith("matplotlib_demo-Copy1.ipynb")
    assert (tmp_path / "matplotlib_demo-Copy1.ipynb").read_text() == src.read_text()


def test_jupyqt_contents_copy_from_strips_leading_slash(tmp_path, monkeypatch):
    """FastAPI passes '/' for POST /api/contents/ — must not become absolute."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.csv").write_bytes(b"data")
    req = _FakeRequest({"copy_from": "x.csv"})

    anyio.run(
        _JupyQtContents.create_content, _FakeContents(), "/", req, None,
    )

    assert (tmp_path / "x-Copy1.csv").read_bytes() == b"data"


def test_jupyqt_contents_copy_from_into_subdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src.csv").write_bytes(b"a,b\n1,2\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    req = _FakeRequest({"copy_from": "src.csv"})

    anyio.run(
        _JupyQtContents.create_content, _FakeContents(), "sub", req, None,
    )

    # No clash in sub/, so keeps the original filename:
    assert (sub / "src.csv").read_bytes() == b"a,b\n1,2\n"


def test_upstream_fps_contents_has_no_files_download_route():
    """fps-contents never registers GET /files/{path} — JupyterLab downloads 404."""
    import inspect

    from fps_contents import routes
    assert "/files/" not in inspect.getsource(routes)


def test_jupyqt_contents_serves_file_with_attachment_disposition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.txt").write_text("hi there\n")

    response = anyio.run(_JupyQtContents._serve_file, _FakeContents(), "/hello.txt")

    assert isinstance(response, FileResponse)
    assert response.filename == "hello.txt"
    # FileResponse sets Content-Disposition to attachment when filename is given:
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert "hello.txt" in disposition
    assert response.path == "hello.txt"


def test_jupyqt_contents_serve_file_missing_returns_404(tmp_path, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.chdir(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        anyio.run(_JupyQtContents._serve_file, _FakeContents(), "/nope.txt")
    assert exc_info.value.status_code == 404


def test_jupyqt_contents_text_path_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = SaveContent(
        name="hello.txt", path="hello.txt", type="file",
        format="text", content="hello\nworld\n",
    )

    anyio.run(_JupyQtContents.write_content, _FakeContents(), payload)

    assert (tmp_path / "hello.txt").read_text() == "hello\nworld\n"
