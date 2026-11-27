# tests/test_launcher.py
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

from jupyqt.server.launcher import ServerLauncher


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


def test_server_provides_nbconvert_formats(shell, tmp_path):
    """The /api/nbconvert endpoint must be served so JupyterLab's
    'Save and Export Notebook As' menu lists export formats."""
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        url = f"http://localhost:{launcher.port}/api/nbconvert?token={launcher.token}"
        req = urllib.request.Request(url)
        deadline = time.time() + 60
        while True:
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert resp.status == 200
                    data = json.loads(resp.read())
                    assert {"html", "pdf", "script"} <= set(data)
                    break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                if time.time() >= deadline:
                    raise
                time.sleep(0.5)
    finally:
        launcher.stop()


def _slow_download(port: int, path: str) -> bytes:
    """GET ``path`` but wait before reading, so the server's send buffer fills up."""
    with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
        sock.sendall(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        time.sleep(0.5)
        chunks = []
        while chunk := sock.recv(1 << 16):
            chunks.append(chunk)
    return b"".join(chunks).partition(b"\r\n\r\n")[2]


def test_large_file_reaches_a_slow_client_whole(shell, tmp_path):
    """Regression: anycorn's zero-copy send cut files short once the socket was full.

    On asyncio, os.sendfile hitting EAGAIN made anycorn call add_writer on a socket
    its transport owns, which raises; Lab's JS chunks failed to load on macOS.
    """
    payload = os.urandom(8 * 1024 * 1024)
    (tmp_path / "big.bin").write_bytes(payload)
    launcher = ServerLauncher(shell, port=0, cwd=str(tmp_path))
    launcher.start()
    try:
        body = _slow_download(launcher.port, f"/files/big.bin?token={launcher.token}")
        assert len(body) == len(payload)
        assert body == payload
    finally:
        launcher.stop()
