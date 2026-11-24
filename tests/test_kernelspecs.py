"""jupyqt runs one in-process kernel; Lab must never be offered another one.

jupyverse lists every kernelspec in the Jupyter data dirs (a user's Julia, the
system python3...), none of which can start here, and Lab then asks which one
to use. jupyqt also used to write its own python3 kernel.json, which landed in
the user data dir when the environment was read-only and shadowed the user's
real python3 kernel in every other Jupyter.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from jupyqt.server.launcher import ServerLauncher


def _request(launcher: ServerLauncher, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://localhost:{launcher.port}{path}?token={launcher.token}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    deadline = time.time() + 60
    while True:
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError):
            if time.time() >= deadline:
                raise
            time.sleep(0.5)


@pytest.fixture
def julia_installed(tmp_path, monkeypatch):
    """A Julia kernelspec on the Jupyter search path, as on Vincent's machine."""
    spec_dir = tmp_path / "jupyter_path" / "kernels" / "julia-1.10"
    spec_dir.mkdir(parents=True)
    (spec_dir / "kernel.json").write_text(json.dumps({
        "argv": ["julia", "{connection_file}"], "display_name": "Julia 1.10", "language": "julia",
    }))
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path / "jupyter_path"))


@pytest.fixture
def server(shell, tmp_path):
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    yield launcher
    launcher.stop()


def test_server_offers_only_the_jupyqt_kernel(julia_installed, server):
    specs = _request(server, "/api/kernelspecs")

    assert specs["default"] == "python3"
    assert list(specs["kernelspecs"]) == ["python3"]
    spec = specs["kernelspecs"]["python3"]["spec"]
    assert (spec["display_name"], spec["language"]) == ("Python 3 (jupyqt)", "python")


def test_session_starts_for_a_kernel_name_without_kernelspec_file(server):
    """No kernel.json is needed: any requested name starts jupyqt's in-process kernel."""
    session = _request(server, "/api/sessions", {
        "kernel": {"name": "no-such-kernel"}, "name": "a.ipynb", "path": "a.ipynb", "type": "notebook",
    })

    assert session["kernel"]["id"]


def test_server_writes_no_kernelspec(shell, tmp_path, monkeypatch):
    prefix, data_dir = tmp_path / "prefix", tmp_path / "data"
    monkeypatch.setattr(
        "jupyqt.server.launcher.sys", SimpleNamespace(prefix=str(prefix), executable="python"), raising=False,
    )
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        _request(launcher, "/api/kernelspecs")
    finally:
        launcher.stop()

    assert list(tmp_path.rglob("kernel.json")) == []
