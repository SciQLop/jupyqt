"""Reproducer for upstream fps-contents base64 upload bug + verification of our fix.

Upstream fps-contents `_Contents.write_content` writes the literal base64
string to disk in the base64 branch instead of decoding it first. Dropping
any binary file into JupyterLab's file browser therefore produces an
ASCII-gibberish file. Our `_JupyQtContents` subclass fixes this.
"""
from __future__ import annotations

import base64
import json
import os
from contextlib import asynccontextmanager
from typing import cast

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

    def file_lock(self, path: str):  # ty: ignore[invalid-method-override]
        return _noop_lock(path)


_BINARY = b"col_a,col_b\n1,2\nbinary:\x00\x01\xfe\xff"


def _make_payload() -> SaveContent:
    return SaveContent(
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
    assert isinstance(payload.content, str)
    assert on_disk == payload.content.encode("ascii")


def test_jupyqt_contents_decodes_base64_and_writes_original_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    anyio.run(_JupyQtContents.write_content, _FakeContents(), _make_payload())

    assert (tmp_path / "sample.csv").read_bytes() == _BINARY


def test_upstream_save_content_model_drops_chunk_field():
    """SaveContent has no `chunk` field, so JupyterLab's chunk number never reaches write_content."""
    parsed = SaveContent(path="x.bin", type="file", format="base64", content="AA==")
    assert not hasattr(parsed, "chunk")


class _FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


_CHUNK_SIZE = 1024 * 1024  # matches JupyterLab's frontend CHUNK_SIZE


def test_jupyqt_contents_assembles_chunked_base64_upload(tmp_path, monkeypatch):
    """Files >1MiB are dropped as a sequence of PUTs tagged chunk=1,2,...,-1 (last).

    Regression test: without chunk-aware assembly, each PUT's base64 branch
    calls write_bytes and overwrites the file, so only the final chunk survives
    on disk instead of the full reassembled upload.
    """
    monkeypatch.chdir(tmp_path)
    data = os.urandom(int(2.5 * _CHUNK_SIZE))
    fake = _FakeContents()

    offset = 0
    chunk_number = 1
    while offset < len(data):
        end = offset + _CHUNK_SIZE
        is_last = end >= len(data)
        body = {
            "path": "dropped.bin",
            "type": "file",
            "format": "base64",
            "chunk": -1 if is_last else chunk_number,
            "content": base64.b64encode(data[offset:end]).decode("ascii"),
        }
        anyio.run(
            _JupyQtContents.save_content, fake, "dropped.bin", _FakeRequest(body), None, None,
        )
        offset = end
        chunk_number += 1

    assert (tmp_path / "dropped.bin").read_bytes() == data


def test_upstream_fps_contents_rejects_copy_from(tmp_path, monkeypatch):
    """Upstream CreateContent model has no copy_from field."""
    from jupyverse_contents.models import CreateContent
    from pydantic import ValidationError
    monkeypatch.chdir(tmp_path)
    body: dict = {"copy_from": "src.csv"}
    with pytest.raises(ValidationError):
        CreateContent(**body)


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


def test_jupyqt_contents_download_route_user_is_dependency_not_query():
    """Regression: the /files/{path} route must resolve `user` as a Depends.

    The Annotated[User, Depends(...)] form is silently not recognized by the
    FastAPI pinned in jupyverse, so the user param falls through to a required
    query parameter and the endpoint returns 422 before the handler runs.
    Inspect the route's dependant to assert `user` is a resolved dependency,
    never a query parameter — this catches a regression without needing httpx.
    """
    import inspect

    src = inspect.getsource(_JupyQtContents.__init__)
    assert "Annotated[User, Depends" not in src, (
        "Annotated form is not recognized by the jupyverse-pinned FastAPI; "
        "use `user: User = Depends(read_user)` instead."
    )
    assert "user: User = Depends(read_user)" in src


def test_jupyqt_contents_text_path_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = SaveContent(
        path="hello.txt", type="file",
        format="text", content="hello\nworld\n",
    )

    anyio.run(_JupyQtContents.write_content, _FakeContents(), payload)

    assert (tmp_path / "hello.txt").read_text() == "hello\nworld\n"


_NOTEBOOK = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def _notebook_payload() -> SaveContent:
    return SaveContent(path="nb.ipynb", type="notebook", format="json",
                       content=json.loads(json.dumps(_NOTEBOOK)))


@pytest.fixture
def notebook_hooks():
    from jupyqt.server.contents import NOTEBOOK_HOOKS
    yield NOTEBOOK_HOOKS
    NOTEBOOK_HOOKS.clear()


def _stamp(_path: str, nb: dict) -> dict:
    return {**nb, "metadata": {**nb["metadata"], "stamp": 1}}


def test_save_hook_rewrites_saved_notebook(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)
    notebook_hooks.add_save_hook(_stamp)

    anyio.run(_JupyQtContents.write_content, _FakeContents(), _notebook_payload())

    assert json.loads((tmp_path / "nb.ipynb").read_text())["metadata"] == {"stamp": 1}


def test_save_hook_receives_absolute_path(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)
    seen = []
    notebook_hooks.add_save_hook(lambda path, nb: seen.append(path) or nb)

    anyio.run(_JupyQtContents.write_content, _FakeContents(), _notebook_payload())

    assert seen == [str(tmp_path / "nb.ipynb")]


def test_failing_save_hook_still_saves_notebook(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)

    def broken(_path, _nb):
        raise RuntimeError("boom")

    notebook_hooks.add_save_hook(broken)
    notebook_hooks.add_save_hook(_stamp)

    anyio.run(_JupyQtContents.write_content, _FakeContents(), _notebook_payload())

    assert json.loads((tmp_path / "nb.ipynb").read_text())["metadata"] == {"stamp": 1}


def test_save_hook_ignores_plain_json_files(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)
    notebook_hooks.add_save_hook(_stamp)
    payload = SaveContent(path="data.json", type="file", format="json", content={"metadata": {}})

    anyio.run(_JupyQtContents.write_content, _FakeContents(), payload)

    assert json.loads((tmp_path / "data.json").read_text()) == {"metadata": {}}


def test_open_hook_fires_when_notebook_content_is_read(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nb.ipynb").write_text(json.dumps({**_NOTEBOOK, "metadata": {"k": "v"}}))
    seen = []
    notebook_hooks.add_open_hook(lambda path, nb: seen.append((path, nb["metadata"])))

    anyio.run(_JupyQtContents.get_content, _FakeContents(), "nb.ipynb", 1)

    assert seen == [(str(tmp_path / "nb.ipynb"), {"k": "v"})]


def test_open_hook_skips_metadata_only_reads(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nb.ipynb").write_text(json.dumps(_NOTEBOOK))
    seen = []
    notebook_hooks.add_open_hook(lambda path, nb: seen.append(path))

    anyio.run(_JupyQtContents.get_content, _FakeContents(), "nb.ipynb", 0)

    assert seen == []


def test_failing_open_hook_still_returns_content(tmp_path, monkeypatch, notebook_hooks):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nb.ipynb").write_text(json.dumps(_NOTEBOOK))

    def broken(_path, _nb):
        raise RuntimeError("boom")

    notebook_hooks.add_open_hook(broken)

    model = anyio.run(_JupyQtContents.get_content, _FakeContents(), "nb.ipynb", 1)

    assert model.type == "notebook"


# JupyterLab asks for images and PDFs with `?format=base64`, but the upstream
# GET route has no `format` parameter, so the server must pick the format itself.
_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
_SVG = '<svg xmlns="http://www.w3.org/2000/svg"/>'


def test_upstream_fps_contents_cannot_read_binary_file(tmp_path, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.chdir(tmp_path)
    (tmp_path / "plot.png").write_bytes(_PNG)

    with pytest.raises(HTTPException):
        anyio.run(_Contents.get_content, _FakeContents(), "plot.png", 1, None)


def test_binary_file_is_served_as_base64_with_its_mimetype(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plot.png").write_bytes(_PNG)

    model = anyio.run(_JupyQtContents.get_content, _FakeContents(), "plot.png", 1)

    assert (model.format, model.mimetype) == ("base64", "image/png")
    assert base64.b64decode(cast("str", model.content)) == _PNG


def test_svg_is_served_as_text_with_image_mimetype(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plot.svg").write_text(_SVG)

    model = anyio.run(_JupyQtContents.get_content, _FakeContents(), "plot.svg", 1)

    assert (model.format, model.mimetype, model.content) == ("text", "image/svg+xml", _SVG)


@pytest.mark.parametrize(("name", "mimetype"), [("data.csv", "text/csv"), ("notes.txt", "text/plain")])
def test_text_file_is_served_as_text(tmp_path, monkeypatch, name, mimetype):
    monkeypatch.chdir(tmp_path)
    (tmp_path / name).write_bytes(b"a,b\n1,2\n")

    model = anyio.run(_JupyQtContents.get_content, _FakeContents(), name, 1)

    assert (model.format, model.mimetype, model.content) == ("text", mimetype, "a,b\n1,2\n")


# jupyqt has a single kernel. A notebook naming another one (or none) would make
# Lab ask which kernel to start, so it is served as a jupyqt-kernel notebook.
def _write_notebook(path, metadata: dict) -> None:
    path.write_text(json.dumps({**_NOTEBOOK, "metadata": metadata}))


def _served_metadata(name: str) -> dict:
    model = anyio.run(_JupyQtContents.get_content, _FakeContents(), name, 1)
    content = model.content
    return (json.loads(content) if isinstance(content, str) else content)["metadata"]


_JULIA = {"kernelspec": {"name": "julia-1.10", "display_name": "Julia 1.10", "language": "julia"},
          "language_info": {"name": "julia"}}


def test_notebook_for_a_foreign_kernel_is_served_with_the_jupyqt_kernel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_notebook(tmp_path / "nb.ipynb", _JULIA)

    kernelspec = _served_metadata("nb.ipynb")["kernelspec"]

    assert (kernelspec["name"], kernelspec["language"]) == ("python3", "python")


def test_notebook_without_kernel_is_served_with_the_jupyqt_kernel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_notebook(tmp_path / "nb.ipynb", {})

    assert _served_metadata("nb.ipynb")["kernelspec"]["name"] == "python3"


def test_python3_notebook_keeps_its_kernelspec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ipykernel = {"name": "python3", "display_name": "Python 3 (ipykernel)", "language": "python"}
    _write_notebook(tmp_path / "nb.ipynb", {"kernelspec": ipykernel})

    assert _served_metadata("nb.ipynb")["kernelspec"] == ipykernel


def test_serving_a_foreign_kernel_notebook_leaves_the_file_and_open_hooks_untouched(
    tmp_path, monkeypatch, notebook_hooks,
):
    monkeypatch.chdir(tmp_path)
    _write_notebook(tmp_path / "nb.ipynb", _JULIA)
    on_disk = (tmp_path / "nb.ipynb").read_text()
    seen = []
    notebook_hooks.add_open_hook(lambda _path, nb: seen.append(nb["metadata"]["kernelspec"]["name"]))

    _served_metadata("nb.ipynb")

    assert (tmp_path / "nb.ipynb").read_text() == on_disk
    assert seen == ["julia-1.10"]


# The fixed upstream route (jupyverse contents-format PR) passes the requested
# format as a 4th positional argument: get_content(path, content, user, format).
def _get_with_format(name: str, file_format: str | None):
    return anyio.run(_JupyQtContents.get_content, _FakeContents(), name, 1, None, file_format)


def test_requested_base64_format_is_honoured_for_a_text_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.csv").write_bytes(b"a,b\n")

    model = _get_with_format("data.csv", "base64")

    assert (model.format, model.mimetype) == ("base64", "text/csv")
    assert base64.b64decode(cast("str", model.content)) == b"a,b\n"


def test_requested_text_format_is_honoured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plot.svg").write_text(_SVG)

    model = _get_with_format("plot.svg", "text")

    assert (model.format, model.mimetype, model.content) == ("text", "image/svg+xml", _SVG)


def test_no_requested_format_keeps_the_utf8_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plot.png").write_bytes(_PNG)

    model = _get_with_format("plot.png", None)

    assert (model.format, model.mimetype) == ("base64", "image/png")


def test_notebook_requested_as_json_still_names_the_jupyqt_kernel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_notebook(tmp_path / "nb.ipynb", _JULIA)

    model = _get_with_format("nb.ipynb", "json")

    assert cast("dict", model.content)["metadata"]["kernelspec"]["name"] == "python3"
