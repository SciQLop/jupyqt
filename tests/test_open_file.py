"""Opening a file in the embedded Lab must not reload Lab when it is already running.

Loading ``/lab/tree/<path>`` reboots the whole Lab page. A running Lab can open
the file itself with its ``docmanager:open`` command, if the page exposes the
app as ``window.jupyterapp`` (``exposeAppInBrowser`` page option).

No Chromium here: the web view is a mock, as in test_widget.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import anyio
import pytest

from jupyqt.qt.widget import JupyterLabWidget, lab_tree_url
from jupyqt.server.lab import expose_app_in_browser
from jupyqt.server.launcher import _build_config

LAB = "http://localhost:1234/lab?token=abc"


@pytest.mark.parametrize(
    ("lab_url", "path", "expected"),
    [
        (LAB, "plot.png", "http://localhost:1234/lab/tree/plot.png?token=abc"),
        (LAB, "sub dir/a.ipynb", "http://localhost:1234/lab/tree/sub%20dir/a.ipynb?token=abc"),
        ("http://localhost:1234/lab/tree/old.png?token=abc", "new.png",
         "http://localhost:1234/lab/tree/new.png?token=abc"),
        ("http://lab.example/lab", "a.txt", "http://lab.example/lab/tree/a.txt"),
    ],
)
def test_lab_tree_url(lab_url, path, expected):
    assert lab_tree_url(lab_url, path) == expected


def test_page_config_hook_exposes_lab_app():
    config: dict = {"exposeAppInBrowser": False}

    anyio.run(expose_app_in_browser, config)

    assert config["exposeAppInBrowser"] is True


def test_server_config_registers_the_lab_module():
    modules = _build_config(0)["jupyverse"]["modules"]

    assert modules["jupyqt_lab"] == {"type": "jupyqt.server.lab:JupyQtLabModule"}


def _fake_widget(*, on_lab: bool) -> MagicMock:
    fake = MagicMock()
    fake.is_on.return_value = on_lab
    return fake


def _run_js_call(fake: MagicMock) -> tuple[str, object]:
    js, _world, callback = fake._web_view.page().runJavaScript.call_args.args
    return js, callback


def test_open_file_in_running_lab_runs_docmanager_open():
    fake = _fake_widget(on_lab=True)

    JupyterLabWidget.open_file(fake, "sub/plot.png", LAB)

    js, callback = _run_js_call(fake)
    assert "docmanager:open" in js
    assert '"sub/plot.png"' in js
    callback(True)  # noqa: FBT003 -- the page's answer
    fake.load.assert_not_called()


def test_open_file_falls_back_to_tree_url_when_page_has_no_lab_app():
    fake = _fake_widget(on_lab=True)

    JupyterLabWidget.open_file(fake, "plot.png", LAB)

    _js, callback = _run_js_call(fake)
    callback(False)  # noqa: FBT003 -- the page's answer
    fake.load.assert_called_once_with("http://localhost:1234/lab/tree/plot.png?token=abc")


def test_open_file_loads_tree_url_when_view_is_not_on_lab():
    fake = _fake_widget(on_lab=False)

    JupyterLabWidget.open_file(fake, "plot.png", LAB)

    fake._web_view.page().runJavaScript.assert_not_called()
    fake.load.assert_called_once_with("http://localhost:1234/lab/tree/plot.png?token=abc")
