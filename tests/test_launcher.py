# tests/test_launcher.py
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from jupyqt.server.launcher import ServerLauncher, _ensure_kernelspec


def test_ensure_kernelspec_creates_kernel_json(tmp_path, monkeypatch):
    monkeypatch.setattr("jupyqt.server.launcher.sys", type("sys", (), {"prefix": str(tmp_path), "executable": "/usr/bin/python3"})())
    _ensure_kernelspec()
    kernel_json = tmp_path / "share" / "jupyter" / "kernels" / "python3" / "kernel.json"
    assert kernel_json.exists()
    spec = json.loads(kernel_json.read_text())
    assert spec["language"] == "python"
    assert spec["display_name"] == "Python 3 (jupyqt)"
    assert spec["argv"][0] == "/usr/bin/python3"


def test_ensure_kernelspec_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr("jupyqt.server.launcher.sys", type("sys", (), {"prefix": str(tmp_path), "executable": "python3"})())
    kernel_dir = tmp_path / "share" / "jupyter" / "kernels" / "python3"
    kernel_dir.mkdir(parents=True)
    existing = {"display_name": "Custom", "language": "python", "argv": ["custom"]}
    (kernel_dir / "kernel.json").write_text(json.dumps(existing))
    _ensure_kernelspec()
    spec = json.loads((kernel_dir / "kernel.json").read_text())
    assert spec["display_name"] == "Custom"


def test_server_starts_and_provides_url(shell, tmp_path):
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        assert launcher.port > 0
        assert launcher.url.startswith("http://localhost:")
        assert launcher.token in launcher.url
    finally:
        launcher.stop()


def test_server_responds_to_http(shell, tmp_path):
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        req = urllib.request.Request(f"http://localhost:{launcher.port}/api/status")
        deadline = time.time() + 60
        while True:
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert resp.status == 200
                    break
            except urllib.error.HTTPError as e:
                # 403 is OK — means server is running but auth is required
                if e.code == 403:
                    break
                raise
            except (urllib.error.URLError, TimeoutError):
                if time.time() >= deadline:
                    raise
                time.sleep(0.5)
    finally:
        launcher.stop()


def test_server_provides_kernelspecs(shell, tmp_path):
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        url = f"http://localhost:{launcher.port}/api/kernelspecs?token={launcher.token}"
        req = urllib.request.Request(url)
        deadline = time.time() + 60
        while True:
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert resp.status == 200
                    data = json.loads(resp.read())
                    assert "kernelspecs" in data
                    assert len(data["kernelspecs"]) > 0
                    break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                if time.time() >= deadline:
                    raise
                time.sleep(0.5)
    finally:
        launcher.stop()
