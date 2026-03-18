# tests/test_launcher.py
from __future__ import annotations

import time
import urllib.request

from jupyqt.server.launcher import ServerLauncher


def test_server_starts_and_provides_url(shell):
    launcher = ServerLauncher(shell, port=0)
    launcher.start()
    try:
        assert launcher.port > 0
        assert launcher.url.startswith("http://localhost:")
        assert launcher.token in launcher.url
    finally:
        launcher.stop()


def test_server_responds_to_http(shell):
    launcher = ServerLauncher(shell, port=0)
    launcher.start()
    try:
        time.sleep(3)  # Give server time to start
        req = urllib.request.Request(f"http://localhost:{launcher.port}/api/status")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                assert resp.status == 200
        except urllib.error.HTTPError as e:
            # 403 is OK — means server is running but auth is required
            assert e.code in (200, 403)  # noqa: PT017
    finally:
        launcher.stop()
