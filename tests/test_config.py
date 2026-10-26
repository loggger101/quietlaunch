# -*- coding: utf-8 -*-
"""LaunchConfig derives its paths from the app, and the CLI fills it in."""

import dataclasses
import os

import pytest

from quietlaunch import launcher
from quietlaunch.launcher import LaunchConfig


def test_paths_derive_from_the_app(tmp_path):
    """Name the script and nothing else: workdir and state live beside it."""
    cfg = LaunchConfig(app=str(tmp_path / "ui.py"))
    assert cfg.workdir == str(tmp_path)
    assert cfg.state_dir == os.path.join(str(tmp_path), ".launcher")
    assert cfg.marker == os.path.join(cfg.state_dir, "running-ui.json")
    assert cfg.log_path(8502) == os.path.join(cfg.state_dir,
                                              "dashboard-8502.log")


def test_relative_paths_are_absolutised_once(tmp_path, monkeypatch):
    """A later chdir must not move where the launcher looks."""
    monkeypatch.chdir(tmp_path)
    cfg = LaunchConfig(app="ui.py", requirements="req.txt")
    monkeypatch.chdir(os.path.dirname(str(tmp_path)))
    assert cfg.app == str(tmp_path / "ui.py")
    assert cfg.requirements == str(tmp_path / "req.txt")


def test_requirements_resolve_against_workdir(tmp_path):
    """A relative requirements file is the project's, not the caller's cwd's."""
    work = tmp_path / "proj"
    cfg = LaunchConfig(app=str(tmp_path / "ui.py"), workdir=str(work),
                       requirements="requirements-ui.txt")
    assert cfg.requirements == str(work / "requirements-ui.txt")


def test_heading_falls_back_to_title(tmp_path):
    """Give a title and the window's bold line says the same."""
    cfg = LaunchConfig(app=str(tmp_path / "a.py"), title="Pipeline")
    assert cfg.window_heading == "Pipeline"
    cfg = LaunchConfig(app=str(tmp_path / "a.py"), title="P", heading="Long")
    assert cfg.window_heading == "Long"


def test_config_is_frozen(tmp_path):
    """Built once: a launcher's config cannot drift while it runs."""
    cfg = LaunchConfig(app=str(tmp_path / "a.py"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.title = "other"


def test_install_args_prefer_an_existing_requirements_file(tmp_path):
    """`-r file` when the file exists, the Streamlit spec when it does not."""
    req = tmp_path / "requirements-ui.txt"
    cfg = LaunchConfig(app=str(tmp_path / "a.py"), requirements=str(req))
    assert launcher._install_args(cfg) == [launcher.STREAMLIT_SPEC]
    req.write_text("streamlit\n", encoding="utf-8")
    assert launcher._install_args(cfg) == ["-r", str(req)]


def test_server_command_is_headless_on_the_port(tmp_path):
    """Streamlit must not open its own browser or wait on a stdin prompt."""
    cfg = LaunchConfig(app=str(tmp_path / "a.py"),
                       streamlit_args=("--theme.base", "dark"))
    cmd = launcher._server_command(cfg, 8600)
    assert cmd[1:5] == ["-m", "streamlit", "run", cfg.app]
    assert "--server.headless=true" in cmd
    assert "--server.port=8600" in cmd
    assert cmd[-2:] == ["--theme.base", "dark"]


def test_cli_fills_every_field(tmp_path, monkeypatch):
    """Each flag lands on its field, and `--` passes the rest to Streamlit."""
    seen = []
    monkeypatch.setattr(launcher, "launch", lambda cfg: seen.append(cfg) or 0)
    app = str(tmp_path / "ui.py")
    rc = launcher.main([app, "--title", "T", "--heading", "H",
                        "--subtitle", "S", "--hint", "slow", "--port", "8600",
                        "--port-tries", "3", "--boot-timeout", "9.5",
                        "--requirements", "r.txt", "--no-install",
                        "--state-dir", str(tmp_path / "st"),
                        "--", "--theme.base", "dark"])
    assert rc == 0
    cfg = seen[0]
    assert (cfg.app, cfg.title, cfg.heading, cfg.subtitle, cfg.boot_hint) == (
        app, "T", "H", "S", "slow")
    assert (cfg.port_first, cfg.port_tries, cfg.boot_timeout_s) == (
        8600, 3, 9.5)
    assert cfg.auto_install is False
    assert cfg.state_dir == str(tmp_path / "st")
    assert cfg.requirements == str(tmp_path / "r.txt")
    assert cfg.streamlit_args == ("--theme.base", "dark")


def test_cli_defaults_match_the_dataclass(tmp_path, monkeypatch):
    """The parser reads its defaults off LaunchConfig rather than retyping them."""
    seen = []
    monkeypatch.setattr(launcher, "launch", lambda cfg: seen.append(cfg) or 0)
    app = str(tmp_path / "ui.py")
    launcher.main([app])
    assert seen[0] == LaunchConfig(app=app)


def test_cli_version_is_the_package_version(capsys):
    """`--version` names the version pyproject.toml reads, and exits 0."""
    import quietlaunch
    with pytest.raises(SystemExit) as exc:
        launcher.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == (
        "quietlaunch " + quietlaunch.__version__)
