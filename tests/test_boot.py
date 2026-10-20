# -*- coding: utf-8 -*-
"""The boot sequence against a fake server: success, failure, reuse, races."""

import dataclasses
import os
import sys

from quietlaunch import launcher
from conftest import wait_for


def status(app):
    """Apply what the worker posted, then read the window's two lines."""
    app._pump_once()
    return app.status.options.get("text"), app.detail.options.get("text")


def test_boot_reports_running_and_opens_the_browser(cfg, fake_mode, browser,
                                                    window):
    """The port answers: marker written, browser opened, Open enabled."""
    app = window(cfg)
    app._boot_inner()
    text, detail = status(app)
    assert text == "The dashboard is running."
    assert detail == "http://localhost:%d" % cfg.port_first
    assert browser == [detail]
    assert app.open_btn.options["state"] == "normal"
    assert launcher._read_marker(cfg) == (cfg.port_first, app.proc.pid)


def test_quit_stops_the_server_and_clears_the_marker(cfg, fake_mode, browser,
                                                     window):
    """The window's close is the server's stop."""
    app = window(cfg)
    app._boot_inner()
    proc = app.proc
    app.quit()
    wait_for(lambda: proc.poll() is not None)
    assert not os.path.exists(cfg.marker)
    assert app.root.destroyed
    assert app.pump_id is None and not app.root.pending
    app.quit()                               # safe to call twice


def test_quit_kills_the_servers_children(cfg, fake_mode, browser, window):
    """An orphaned child holds the port, and the next launch moves to 8502."""
    fake_mode("parent")
    app = window(cfg)
    app._boot_inner()
    assert status(app)[0] == "The dashboard is running."
    with open(cfg.log_path(cfg.port_first), encoding="utf-8") as f:
        child = int(f.read().split("child pid ")[1].split()[0])
    assert launcher._pid_alive(child)
    app.quit()
    wait_for(lambda: not launcher._pid_alive(child))
    wait_for(lambda: not launcher._port_answers(cfg.port_first))


def test_a_server_that_dies_reports_its_log(cfg, fake_mode, browser, window):
    """Under pythonw the log tail IS the error report."""
    fake_mode("die")
    app = window(cfg)
    app._boot_inner()
    text, detail = status(app)
    assert text == "The server stopped while starting up."
    assert "planted_failure" in detail
    assert browser == []
    assert not os.path.exists(cfg.marker)


def test_a_server_that_never_answers_times_out(cfg, fake_mode, browser,
                                               window):
    """A hang is reported as one, and the marker never advertises it."""
    fake_mode("hang")
    app = window(dataclasses.replace(cfg, boot_timeout_s=1.0))
    app._boot_inner()
    text, _ = status(app)
    assert text == "The server did not come up within 1 seconds."
    assert not os.path.exists(cfg.marker)


def test_a_second_launch_reuses_and_goes_away(cfg, fake_mode, browser,
                                              window):
    """One dashboard, one control window: the second reopens and quits."""
    first = window(cfg)
    first._boot_inner()
    second = window(cfg)
    second._boot_inner()
    text, _ = status(second)
    assert text.startswith("Already running")
    assert second.proc is None
    assert browser[-1] == "http://localhost:%d" % cfg.port_first
    assert first.proc.poll() is None         # the first one's server untouched


def test_closing_mid_spawn_never_leaks_the_server(cfg, fake_mode, browser,
                                                  window, monkeypatch):
    """The hand-over race: closed between Popen and the assignment."""
    app = window(cfg)
    real = launcher._start_streamlit
    spawned = []

    def spawn_then_close(c, port):
        """Popen returns with the child alive; the user closes right then."""
        proc, log = real(c, port)
        spawned.append(proc)
        app.quit()
        return proc, log
    monkeypatch.setattr(launcher, "_start_streamlit", spawn_then_close)
    app._boot_inner()
    wait_for(lambda: spawned[0].poll() is not None)
    assert app.proc is None


def test_a_missing_app_is_named(cfg, fake_mode, window):
    """The one failure that needs no server to report."""
    app = window(dataclasses.replace(cfg, app=cfg.app + ".gone"))
    app._boot_inner()
    text, detail = status(app)
    assert text == "app.py.gone was not found."
    assert detail.endswith("app.py.gone")


def test_no_streamlit_and_no_install_says_so(cfg, window, monkeypatch):
    """auto_install=False: say what to run instead of running it."""
    monkeypatch.setattr(launcher, "_streamlit_installed", lambda: False)
    app = window(cfg)
    app._boot_inner()
    text, detail = status(app)
    assert text == "Streamlit is not installed."
    assert launcher.STREAMLIT_SPEC in detail


def test_a_failed_install_reports_pips_output(cfg, window, monkeypatch):
    """The install log's tail reaches the window, not just its path."""
    monkeypatch.setattr(launcher, "_streamlit_installed", lambda: False)

    def failing_install(c):
        """Write what pip would have, then fail."""
        os.makedirs(c.state_dir, exist_ok=True)
        with open(launcher._install_log(c), "w", encoding="utf-8") as f:
            f.write("ERROR: No matching distribution found for streamlit\n")
        return False
    monkeypatch.setattr(launcher, "_pip_install_streamlit", failing_install)
    app = window(dataclasses.replace(cfg, auto_install=True))
    app._boot_inner()
    text, detail = status(app)
    assert text == "Could not install Streamlit."
    assert "No matching distribution" in detail


def test_without_tkinter_a_dead_server_is_reported(cfg, fake_mode, browser,
                                                   monkeypatch):
    """The no-window fallback says what happened, not what was hoped for."""
    fake_mode("die")
    boxes = []
    monkeypatch.setattr(launcher, "_message_box",
                        lambda title, text: boxes.append((title, text)))
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert launcher.launch(cfg) == 1
    assert boxes[0][0] == "Test"
    assert "stopped while starting up" in boxes[0][1]
    assert "planted_failure" in boxes[0][1]
    assert browser == []


def test_without_tkinter_a_live_server_opens_the_browser(cfg, fake_mode,
                                                         browser,
                                                         monkeypatch):
    """Up, but nothing to close: say so, and where to stop it."""
    boxes = []
    monkeypatch.setattr(launcher, "_message_box",
                        lambda title, text: boxes.append((title, text)))
    monkeypatch.setitem(sys.modules, "tkinter", None)
    try:
        assert launcher.launch(cfg) == 0
        assert browser == ["http://localhost:%d" % cfg.port_first]
        assert "Task Manager" in boxes[0][1]
    finally:
        port, pid = launcher._read_marker(cfg)
        if pid:
            import subprocess
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, 9)
