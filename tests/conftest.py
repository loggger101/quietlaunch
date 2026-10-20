# -*- coding: utf-8 -*-
"""Shared fixtures: a fake server, free ports, and Tk stand-ins.

The Tk stand-ins exist because `Launcher` takes `tk` and `ttk` as arguments,
which lets the whole boot sequence run on a CI runner with no display. They
record what the window would show; they do not pretend to lay anything out.
"""

import os
import socket
import subprocess
import sys

import pytest

from quietlaunch import launcher

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "fake_streamlit.py")


def free_port():
    """A port nothing holds right now, BELOW every OS's ephemeral range.

    Not `bind(0)`: that hands out an ephemeral port, and macOS allocates those
    in sequence, so the port a test picked (and the one after it) is what the
    next client socket takes as its own source port -- including the
    launcher's own probe of it. The tests then saw ports held, or a probe
    connected to itself, on macOS runners only. 20000-32000 sits below the
    ephemeral ranges of Windows and macOS (49152+) and Linux (32768+), as
    Streamlit's real 8501 does.
    """
    import random
    rng = random.Random()
    for _ in range(200):
        port = rng.randrange(20000, 32000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("no free port found below the ephemeral range")


@pytest.fixture
def cfg(tmp_path):
    """A LaunchConfig for an app in a temp folder, on a port the OS picked."""
    app = tmp_path / "app.py"
    app.write_text("# a Streamlit app\n", encoding="utf-8")
    return launcher.LaunchConfig(app=str(app), title="Test",
                                 port_first=free_port(), port_tries=1,
                                 boot_timeout_s=20.0, auto_install=False)


@pytest.fixture
def fake_mode(monkeypatch):
    """Point `_server_command` at the fake server; returns a setter for its mode."""
    state = {"mode": "serve"}
    monkeypatch.setattr(
        launcher, "_server_command",
        lambda cfg, port: [sys.executable, FAKE, str(port), state["mode"]])
    monkeypatch.setattr(launcher, "_streamlit_installed", lambda: True)

    def set_mode(mode):
        """Choose what the next spawned server does."""
        state["mode"] = mode
    return set_mode


@pytest.fixture
def browser(monkeypatch):
    """Capture `webbrowser.open` instead of opening anything."""
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    return opened


@pytest.fixture
def serve_other(tmp_path):
    """Start a fake Streamlit this launcher did NOT start; yields its port."""
    procs = []

    def start(port, mode="serve"):
        """Spawn a stranger's server on `port` and wait until it answers."""
        log = tmp_path / ("other-%d.log" % port)
        with open(log, "w", encoding="utf-8") as out:
            p = subprocess.Popen([sys.executable, FAKE, str(port), mode],
                                 stdout=out, stderr=subprocess.STDOUT)
        procs.append(p)
        wait_for(lambda: launcher._port_answers(port),
                 why=lambda: "fake server on %d (exit %s) said: %r"
                 % (port, p.poll(), log.read_text(encoding="utf-8")))
        return p
    yield start
    for p in procs:
        launcher._stop(p)


def wait_for(cond, timeout=15.0, why=None):
    """Poll `cond` until true; fail the test if it never is, saying `why()`."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("condition never became true"
                         + (": " + why() if why else ""))


# ---------------------------------------------------------------- Tk stand-ins

class _Widget(object):
    """Records `configure` calls; every layout method is a no-op."""

    def __init__(self, *args, **kw):
        """Keep the construction options; `text` is what a test reads."""
        self.options = dict(kw)

    def configure(self, **kw):
        """Remember the latest options, as Tk would display them."""
        self.options.update(kw)

    def pack(self, *a, **kw):
        """No layout."""

    def pack_forget(self):
        """No layout."""

    def start(self, *a):
        """Progress bar animation: nothing to animate."""

    def stop(self):
        """Progress bar animation: nothing to stop."""


class FakeRoot(object):
    """The `Tk()` surface `Launcher` touches, with `after` callbacks held."""

    def __init__(self):
        """No window, no event loop; `after` returns ids and remembers them."""
        self.pending = {}
        self.destroyed = False
        self._next = 0

    def title(self, *a):
        """Window title: ignored."""

    def geometry(self, *a):
        """Window size: ignored."""

    def minsize(self, *a):
        """Window size: ignored."""

    def protocol(self, *a):
        """Close-button hook: the tests call `quit` directly."""

    def after(self, ms, fn):
        """Hold the callback; nothing runs it unless a test does."""
        self._next += 1
        self.pending[self._next] = fn
        return self._next

    def after_cancel(self, ident):
        """Drop a held callback."""
        self.pending.pop(ident, None)

    def update_idletasks(self):
        """Nothing to redraw."""

    def destroy(self):
        """Mark the window gone."""
        self.destroyed = True


class FakeTtk(object):
    """`ttk` with every widget class replaced by `_Widget`."""
    Frame = Label = Progressbar = Button = _Widget


@pytest.fixture
def window():
    """Build a `Launcher` over the stand-ins: `window(cfg)` returns it."""
    made = []

    def build(cfg):
        """A Launcher whose widgets record instead of draw."""
        app = launcher.Launcher(cfg, FakeRoot(), None, FakeTtk)
        made.append(app)
        return app
    yield build
    for app in made:                         # never leak a server on failure
        with app.lock:
            proc = app.proc
        launcher._stop(proc)
