# tests/conftest.py
"""Shared fixtures for jupyqt tests."""

from __future__ import annotations

import pytest
from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.shell import create_shell


@pytest.fixture
def shell():
    """Create a fresh InteractiveShell, cleaning up the singleton after."""
    s = create_shell()
    yield s
    InteractiveShell.clear_instance()
