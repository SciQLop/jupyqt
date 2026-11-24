# tests/conftest.py
"""Shared fixtures for jupyqt tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.shell import create_shell


@pytest.fixture
def shell(tmp_path, monkeypatch):
    """Create a fresh InteractiveShell, cleaning up the singleton after."""
    # Use a per-worker temp dir for IPython to avoid SQLite "database is locked"
    # errors when pytest-xdist runs multiple workers concurrently.
    monkeypatch.setenv("IPYTHONDIR", str(tmp_path / "ipython"))
    s = create_shell()
    yield s
    InteractiveShell.clear_instance()


@pytest.fixture(autouse=True)
def _isolated_kernelspec_cleanup(tmp_path, monkeypatch):
    """Keep the server's old-kernelspec cleanup off the real sys.prefix and user data dir."""
    monkeypatch.setattr("jupyqt.server.kernelspec.sys", SimpleNamespace(prefix=str(tmp_path / "prefix")))
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter_data"))
