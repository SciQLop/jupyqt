"""jupyqt runs one in-process kernel; Lab must never be offered another one.

jupyverse lists every kernelspec in the Jupyter data dirs (a user's Julia, the
system python3...), none of which can start here, and Lab then asks which one
to use. jupyqt also used to write its own python3 kernel.json, which landed in
the user data dir when the environment was read-only and shadowed the user's
real python3 kernel in every other Jupyter.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from jupyqt.server.kernelspec import remove_old_jupyqt_kernelspec
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


# Older jupyqt (0.4.0 to 0.6.6, and an unreleased branch) wrote a broken python3
# kernel.json. It is removed only when it is byte-for-byte what jupyqt wrote.
def _old_jupyqt_text(argv0: str) -> str:
    """Exactly what older jupyqt wrote: json.dumps(spec, indent=1) + newline."""
    spec = {
        "argv": [argv0, "-m", "jupyqt", "-f", "{connection_file}"],
        "display_name": "Python 3 (jupyqt)",
        "language": "python",
    }
    return json.dumps(spec, indent=1) + "\n"


def _kernel_dir(root, text: str | None = None):
    kernel_dir = root / "kernels" / "python3"
    kernel_dir.mkdir(parents=True)
    if text is not None:
        (kernel_dir / "kernel.json").write_text(text, encoding="utf-8")
    return kernel_dir


@pytest.mark.parametrize(
    "argv0",
    ["/opt/sciqlop/bin/python3.12", "python3", "C:\\Program Files\\SciQLop\\python.exe"],
)
def test_old_jupyqt_kernelspec_is_removed_with_its_empty_folder(tmp_path, argv0):
    kernel_dir = _kernel_dir(tmp_path, _old_jupyqt_text(argv0))

    remove_old_jupyqt_kernelspec(kernel_dir)

    assert not kernel_dir.exists()
    assert (tmp_path / "kernels").exists(), "only the python3 folder may go"


def test_folder_with_other_files_is_kept(tmp_path):
    kernel_dir = _kernel_dir(tmp_path, _old_jupyqt_text("python3"))
    (kernel_dir / "logo-64x64.png").write_bytes(b"png")

    remove_old_jupyqt_kernelspec(kernel_dir)

    assert sorted(p.name for p in kernel_dir.iterdir()) == ["logo-64x64.png"]


_OLD = json.loads(_old_jupyqt_text("/usr/bin/python3"))
_NEAR_MISSES = {
    "ipykernel spec": json.dumps({
        "argv": ["python", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Python 3 (ipykernel)", "language": "python",
    }, indent=1) + "\n",
    "extra key": json.dumps({**_OLD, "metadata": {}}, indent=1) + "\n",
    "other display name": json.dumps({**_OLD, "display_name": "Python 3"}, indent=1) + "\n",
    "other language": json.dumps({**_OLD, "language": "Python"}, indent=1) + "\n",
    "extra argv": json.dumps({**_OLD, "argv": [*_OLD["argv"], "--debug"]}, indent=1) + "\n",
    "other module": json.dumps({**_OLD, "argv": ["python", "-m", "jupyqtx", "-f", "{connection_file}"]},
                               indent=1) + "\n",
    "argv0 not a string": json.dumps({**_OLD, "argv": [None, *_OLD["argv"][1:]]}, indent=1) + "\n",
    "missing key": json.dumps({k: v for k, v in _OLD.items() if k != "language"}, indent=1) + "\n",
    "reformatted": json.dumps(_OLD, indent=2) + "\n",
    "no final newline": json.dumps(_OLD, indent=1),
    "key order changed": json.dumps(dict(reversed(list(_OLD.items()))), indent=1) + "\n",
    "not json": "not json\n",
    "empty": "",
}


@pytest.mark.parametrize("text", _NEAR_MISSES.values(), ids=_NEAR_MISSES.keys())
def test_near_miss_kernelspec_is_kept(tmp_path, text):
    kernel_dir = _kernel_dir(tmp_path, text)

    remove_old_jupyqt_kernelspec(kernel_dir)

    assert (kernel_dir / "kernel.json").read_text(encoding="utf-8") == text


def test_symlinked_kernel_json_is_kept_with_its_target(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text(_old_jupyqt_text("python3"), encoding="utf-8")
    kernel_dir = _kernel_dir(tmp_path)
    (kernel_dir / "kernel.json").symlink_to(target)

    remove_old_jupyqt_kernelspec(kernel_dir)

    assert (kernel_dir / "kernel.json").is_symlink()
    assert target.read_text(encoding="utf-8") == _old_jupyqt_text("python3")


def test_symlinked_python3_folder_is_kept_with_its_target(tmp_path):
    real = _kernel_dir(tmp_path / "real", _old_jupyqt_text("python3"))
    (tmp_path / "kernels").mkdir()
    (tmp_path / "kernels" / "python3").symlink_to(real, target_is_directory=True)

    remove_old_jupyqt_kernelspec(tmp_path / "kernels" / "python3")

    assert (real / "kernel.json").exists()
    assert (tmp_path / "kernels" / "python3").is_symlink()


def test_missing_folder_is_fine(tmp_path):
    remove_old_jupyqt_kernelspec(tmp_path / "kernels" / "python3")


def test_removal_is_logged(tmp_path, caplog):
    kernel_dir = _kernel_dir(tmp_path, _old_jupyqt_text("python3"))

    with caplog.at_level(logging.INFO, logger="jupyqt.server.kernelspec"):
        remove_old_jupyqt_kernelspec(kernel_dir)

    assert str(kernel_dir / "kernel.json") in caplog.text


def test_server_start_cleans_only_the_two_places_old_jupyqt_wrote_to(shell, tmp_path, monkeypatch):
    prefix, data_dir, other = tmp_path / "prefix", tmp_path / "data", tmp_path / "other"
    old = _old_jupyqt_text("python3")
    prefix_dir = _kernel_dir(prefix / "share" / "jupyter", old)
    user_dir = _kernel_dir(data_dir, old)
    other_dir = _kernel_dir(other, old)
    julia_dir = data_dir / "kernels" / "julia-1.10"
    julia_dir.mkdir()
    (julia_dir / "kernel.json").write_text(old, encoding="utf-8")
    monkeypatch.setattr("jupyqt.server.kernelspec.sys", SimpleNamespace(prefix=str(prefix)))
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JUPYTER_PATH", str(other))
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        _request(launcher, "/api/kernelspecs")
    finally:
        launcher.stop()

    assert not prefix_dir.exists()
    assert not user_dir.exists()
    assert (other_dir / "kernel.json").exists(), "other Jupyter paths are never touched"
    assert (julia_dir / "kernel.json").exists(), "only the python3 folder is looked at"
