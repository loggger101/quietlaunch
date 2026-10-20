# -*- coding: utf-8 -*-
"""Ports, pids and the marker: when a running server is ours to reuse."""

import json
import os
import socket
import subprocess
import sys

from quietlaunch import launcher
from conftest import free_port


def _listener(host, reuse):
    """A bare listening socket, set up the way a web server sets one up."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if reuse:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, 0 if host == "127.0.0.1" else free_port()))
    s.listen(1)
    return s


def test_a_listening_port_is_neither_free_nor_silent():
    """The SO_REUSEADDR trap: on Windows that flag made a held port look free.

    Measured on Windows 11: a SO_REUSEADDR probe binds over a listener only
    when the listener set the flag too, which Python's `http.server` does. So
    the listener here sets it; one that does not would pass this test with
    the trap planted. Linux refuses either way, so this bites on Windows only.
    """
    with _listener("127.0.0.1", reuse=True) as s:
        port = s.getsockname()[1]
        assert launcher._port_answers(port)
        assert not launcher._port_is_free(port)


def test_a_wildcard_listener_is_skipped_although_the_port_binds(cfg):
    """Ask "is someone there" before "can I bind": the order is load-bearing.

    On Windows a server on 0.0.0.0 does not stop a plain bind on 127.0.0.1,
    so a bindability probe alone would start a second server on its port.
    """
    import dataclasses
    with _listener("0.0.0.0", reuse=False) as s:
        port = s.getsockname()[1]
        two = dataclasses.replace(cfg, port_first=port, port_tries=2)
        got, running = launcher._choose_port(two)
        assert not running
        assert got != port


def test_an_unused_port_is_free_and_silent():
    """Nothing there: no answer, and we can bind it."""
    port = free_port()
    assert not launcher._port_answers(port)
    assert launcher._port_is_free(port)


def test_pid_alive_for_this_process_and_not_for_a_finished_one():
    """A live pid reads alive; an exited child reads gone."""
    assert launcher._pid_alive(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not launcher._pid_alive(p.pid)


def test_console_python_swaps_pythonw_for_python(tmp_path, monkeypatch):
    """Under pythonw the child gets the console interpreter beside it."""
    pyw = tmp_path / "pythonw.exe"
    py = tmp_path / "python.exe"
    pyw.write_bytes(b"")
    py.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(pyw))
    assert launcher._console_python() == str(py)


def test_console_python_keeps_pythonw_when_no_python_beside_it(tmp_path,
                                                               monkeypatch):
    """No console interpreter to swap to: keep what is running."""
    pyw = tmp_path / "pythonw.exe"
    pyw.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(pyw))
    assert launcher._console_python() == str(pyw)


def test_marker_round_trip(cfg):
    """What one launch writes, the next reads back."""
    launcher._write_marker(cfg, 8555, 4242)
    assert launcher._read_marker(cfg) == (8555, 4242)
    launcher._clear_marker(cfg)
    assert launcher._read_marker(cfg) == (None, None)
    launcher._clear_marker(cfg)              # a missing file is fine


def test_a_bad_marker_means_no_server(cfg):
    """A truncated or hand-edited note is a hint that failed, never an error."""
    os.makedirs(cfg.state_dir, exist_ok=True)
    with open(cfg.marker, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert launcher._read_marker(cfg) == (None, None)


def test_a_marker_for_another_app_is_not_ours(cfg, tmp_path):
    """Same file name, another folder's script, one shared state_dir."""
    other = launcher.LaunchConfig(app=str(tmp_path / "elsewhere" / "app.py"),
                                  state_dir=cfg.state_dir)
    assert other.marker == cfg.marker
    launcher._write_marker(other, 8555, os.getpid())
    assert launcher._read_marker(cfg) == (None, None)


def test_choose_port_skips_a_port_someone_holds(cfg, serve_other):
    """A stranger's Streamlit on the first port is left alone."""
    serve_other(cfg.port_first)
    import dataclasses
    two = dataclasses.replace(cfg, port_tries=2)
    port, running = launcher._choose_port(two)
    assert not running
    assert port != cfg.port_first


def test_a_strangers_streamlit_is_not_adopted(cfg, serve_other):
    """Healthy is not ours: no marker, no reuse."""
    serve_other(cfg.port_first)
    port, running = launcher._choose_port(cfg)
    assert not running


def test_our_live_server_is_reused(cfg, serve_other):
    """Marker, live pid AND a healthy port: reopen rather than start again."""
    p = serve_other(cfg.port_first)
    launcher._write_marker(cfg, cfg.port_first, p.pid)
    assert launcher._choose_port(cfg) == (cfg.port_first, True)


def test_a_dead_pids_marker_is_not_adopted_although_the_port_answers(
        cfg, serve_other):
    """A crash leaves a note; a stranger later takes the port. Not ours."""
    serve_other(cfg.port_first)
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    launcher._write_marker(cfg, cfg.port_first, p.pid)
    assert launcher._choose_port(cfg)[1] is False


def test_a_live_pid_on_a_port_that_is_not_streamlit_is_not_adopted(cfg):
    """The pid was recycled onto a live process, and the port answers, but
    with something that is not Streamlit: the health check is what says no."""
    with _listener("127.0.0.1", reuse=False) as s:
        port = s.getsockname()[1]
        import dataclasses
        mine = dataclasses.replace(cfg, port_first=port)
        launcher._write_marker(mine, port, os.getpid())
        assert launcher._choose_port(mine)[1] is False


def test_a_marker_whose_pid_died_is_cleared(cfg):
    """A crash leaves a note; the dead pid retires it."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    launcher._write_marker(cfg, cfg.port_first, p.pid)
    port, running = launcher._choose_port(cfg)
    assert not running
    assert not os.path.exists(cfg.marker)


def test_another_apps_marker_survives_our_launch(cfg, tmp_path):
    """Its note is not ours to delete, even though we cannot use it."""
    other = launcher.LaunchConfig(app=str(tmp_path / "elsewhere" / "app.py"),
                                  state_dir=cfg.state_dir)
    launcher._write_marker(other, 8555, os.getpid())
    launcher._choose_port(cfg)
    with open(cfg.marker, encoding="utf-8") as f:
        assert json.load(f)["app"] == other.app
