"""JupyterLab's File menu can kill the server; jupyqt must be able to relaunch.

"Shut Down" reaches fps_lab's shutdown route, which exits the whole fps app —
the jupyqt-server thread ends and the launcher is dead. Before this was handled,
_ensure_server() only checked `self._launcher is not None`, so every later
widget()/open_in_browser() reused the corpse and the panel could never come
back (SciQLop/jupyqt#10).
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from jupyqt.api import EmbeddedJupyter


class FakeLauncher:
    """Stands in for ServerLauncher: no thread, no server, scriptable liveness."""

    instances: ClassVar[list[FakeLauncher]] = []

    def __init__(self, shell, kernel_thread=None, port=0, cwd=None):
        self.shell = shell
        self.kernel_thread = kernel_thread
        self.cwd = cwd
        self.port = port or 1234 + len(FakeLauncher.instances)
        self.started = False
        self.stopped = False
        self.alive = False
        FakeLauncher.instances.append(self)

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}/lab?token=fake"

    @property
    def is_running(self) -> bool:
        return self.alive

    def start(self) -> None:
        self.started = True
        self.alive = True

    def stop(self) -> None:
        self.stopped = True
        self.alive = False


@pytest.fixture
def fake_launcher(monkeypatch):
    FakeLauncher.instances = []
    monkeypatch.setattr("jupyqt.server.launcher.ServerLauncher", FakeLauncher)
    return FakeLauncher


@pytest.fixture
def embedded(fake_launcher):
    ej = EmbeddedJupyter()
    ej._started = True  # skip the real kernel thread; only server lifecycle is under test
    return ej


def test_ensure_server_starts_one_launcher(embedded, fake_launcher):
    embedded._ensure_server()

    assert len(fake_launcher.instances) == 1
    assert fake_launcher.instances[0].started


def test_ensure_server_reuses_a_live_launcher(embedded, fake_launcher):
    embedded._ensure_server()
    embedded._ensure_server()

    assert len(fake_launcher.instances) == 1


def test_ensure_server_replaces_a_dead_launcher(embedded, fake_launcher):
    embedded._ensure_server()
    dead = fake_launcher.instances[0]

    dead.alive = False  # what Lab's "Shut Down" leaves behind
    embedded._ensure_server()

    assert len(fake_launcher.instances) == 2, "a dead server must be relaunched"
    assert fake_launcher.instances[1].started
    assert dead.stopped, "the dead launcher's thread must be joined"


def test_url_after_relaunch_points_at_the_new_server(embedded, fake_launcher):
    embedded._ensure_server()
    old_url = embedded._launcher.url

    fake_launcher.instances[0].alive = False
    embedded._ensure_server()

    assert embedded._launcher.url != old_url
    assert embedded._launcher is fake_launcher.instances[1]


def test_shutdown_then_ensure_server_starts_a_fresh_one(embedded, fake_launcher):
    embedded._ensure_server()
    embedded._launcher.stop()
    embedded._launcher = None  # what EmbeddedJupyter.shutdown() does
    embedded._started = True

    embedded._ensure_server()

    assert len(fake_launcher.instances) == 2
    assert fake_launcher.instances[1].is_running


class FakeWidget:
    """Stands in for JupyterLabWidget: records loads, fakes the committed URL."""

    def __init__(self):
        self.loads: list[str] = []
        self.showing = ""

    def load(self, url: str) -> None:
        self.loads.append(url)
        self.showing = url

    def is_on(self, url_prefix: str) -> bool:
        return self.showing.startswith(url_prefix)


@pytest.fixture
def fake_widget(monkeypatch):
    monkeypatch.setattr("jupyqt.qt.widget.JupyterLabWidget", FakeWidget)


def test_widget_loads_lab_on_first_call(embedded, fake_widget):
    w = embedded.widget()

    assert w.loads == [embedded._launcher.url]


def test_widget_does_not_reload_a_live_lab_page(embedded, fake_widget):
    w = embedded.widget()
    w.showing = f"{embedded._launcher.url.split('?')[0]}/tree/notebook.ipynb"

    embedded.widget()

    assert len(w.loads) == 1, "re-showing the panel must not discard Lab's state"


def test_widget_recovers_from_the_logout_page(embedded, fake_widget):
    w = embedded.widget()
    w.showing = f"http://localhost:{embedded._launcher.port}/logout"

    embedded.widget()

    assert w.loads[-1] == embedded._launcher.url


def test_widget_follows_the_server_across_a_restart(embedded, fake_launcher, fake_widget):
    w = embedded.widget()
    fake_launcher.instances[0].alive = False

    embedded.widget()

    assert w.loads[-1] == fake_launcher.instances[1].url


def test_real_launcher_reports_not_running_before_start():
    from jupyqt.server.launcher import ServerLauncher

    # the shell is only touched once the server thread runs, which it never does here
    launcher = ServerLauncher(shell=None, port=12345)  # ty: ignore[invalid-argument-type]

    assert launcher.is_running is False
