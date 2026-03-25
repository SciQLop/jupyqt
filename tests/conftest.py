# tests/conftest.py
"""Shared fixtures for jupyqt tests."""

from __future__ import annotations

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
