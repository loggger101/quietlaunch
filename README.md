# quietlaunch

[![tests](https://github.com/loggger101/quietlaunch/actions/workflows/tests.yml/badge.svg)](https://github.com/loggger101/quietlaunch/actions/workflows/tests.yml)

Start a Streamlit app with **no console window**, and give it something to close.

`streamlit run app.py` in a terminal makes the terminal the app: close it and the
server stops, leave it and it sits in the way. Hiding it with `pythonw` is worse:
a failed start becomes a program that silently never appears, and a working one
is a server nobody can stop without Task Manager. quietlaunch replaces the
console with a small control window that

- says what is happening while the server boots, and why it failed if it does
  (the server log's last lines, not "something went wrong");
- opens the browser once the port actually answers, not when the process starts;
- reuses the dashboard it started earlier instead of booting a second copy, and
  never adopts somebody else's Streamlit that happens to hold the port;
- stops the server **and its children** when it is closed;
- installs Streamlit on first use if the interpreter does not have it.

Python 3.9 or later, standard library only. Windows is the reason it exists;
Linux and macOS work too, and CI runs all three (tkinter required for the
window; without it there is a message-box fallback).

Extracted from [economicspace](https://github.com/loggger101/economicspace)'s
dashboard launcher, whose history this repository carries.

## Install

```bash
pip install "quietlaunch @ git+https://github.com/loggger101/quietlaunch@v0.1.0"
```

## Use

From a shortcut or a double-clicked script, with no console:

```bash
pythonw -m quietlaunch path/to/app.py --title "My dashboard"
```

`python -m quietlaunch ...` is the same with a console to watch. The installed
`quietlaunch` command is a GUI script, so on Windows it starts windowless too.
Everything after `--` goes to `streamlit run`:

```bash
pythonw -m quietlaunch app.py --port 8600 -- --theme.base dark
```

From a project's own launcher, which is how economicspace uses it:

```python
import sys
import quietlaunch

sys.exit(quietlaunch.launch(quietlaunch.LaunchConfig(
    app="ui.py",
    title="Asteroid Pipeline",
    heading="Asteroid mining profitability pipeline",
    boot_hint="First run loads the pipeline, which takes a minute.",
    requirements="requirements-ui.txt",
)))
```

`python -m quietlaunch --help` lists every option; each sets a `LaunchConfig`
field:

| field | flag | default | what |
|---|---|---|---|
| `app` | positional | (required) | the Streamlit script |
| `title`, `heading`, `subtitle` | `--title`, `--heading`, `--subtitle` | `Streamlit`, title, `Dashboard` | window text |
| `boot_hint` | `--hint` | empty | shown while the server boots |
| `workdir` | `--workdir` | the app's folder | the server's working directory |
| `state_dir` | `--state-dir` | `<workdir>/.launcher` | logs and the running-server marker; gitignore it |
| `port_first`, `port_tries` | `--port`, `--port-tries` | `8501`, `12` | ports tried, upwards |
| `boot_timeout_s` | `--boot-timeout` | `300` | how long a boot may take |
| `auto_install` | `--no-install` | `True` | first-run `pip install` when Streamlit is missing |
| `requirements` | `--requirements` | none | install from this file (relative to `workdir`) instead of `streamlit>=1.30`; a missing file falls back to that spec |
| `streamlit_args` | after `--` | none | extra `streamlit run` arguments |

What it leaves in `state_dir`: `dashboard-<port>.log` (the server's output),
`install.log` (the first-run install), and `running-<app>.json` (the port, pid
and app of the server it started; deleted when that server stops).

## Why it looks the way it does

Each of these was hit for real, and each looks fine from a console. The tests
plant every one and fail on it.

- **`SO_REUSEADDR` is inverted on Windows.** On Unix it means "reuse a port in
  TIME_WAIT"; on Windows it means "bind even though someone holds it", so a
  free-port probe that sets it calls a live server's port free. The probe does a
  bare `bind`, and asks "does anything answer here?" **first**, since on Windows
  a server on `0.0.0.0` does not even stop a plain bind on `127.0.0.1`.
- **A health check identifies Streamlit, not your Streamlit.** Reuse requires
  the marker, a live pid **and** a healthy port: a crashed launcher, a recycled
  pid and a stranger's app each fail a different one. The marker is per app, so
  two apps in one folder do not adopt, or delete the note of, each other's server.
- **A busy dashboard answers its health check late.** The app's script runs in
  the server's process; during a page load `/_stcore/health` took 4.4 s on the
  dashboard this came from. A 1 s check read our own server as a stranger and
  booted a second one, so reuse waits up to 15 s (`REUSE_HEALTH_TIMEOUT_S`).
- **`Tk.after` is not thread-safe**, and raises once the main loop is gone. The
  boot thread never touches a widget; it posts callables to a queue the main
  thread drains, and `quit()` cancels the pending drain rather than letting it
  fire into a destroyed interpreter.
- **Closing the window mid-spawn leaked a server.** `Popen` returns with the
  child alive, so the hand-over to the window is made atomic with a lock, and
  the boot thread is joined after `mainloop()`: it is a daemon, and without the
  join the process exits before the lock ever matters.
- **Killing the spawned pid is not killing the server.** Streamlit's file
  watcher and the app's own worker processes hold the port. Windows uses
  `taskkill /T`; POSIX starts the server in its own session and kills the group.
- **Under `pythonw`, `sys.executable` has no stdout.** The server and the pip
  install are run with the console `python` beside it, redirected to a log, so
  the log is real and its tail can be shown.
- **Without tkinter, report what happened, not what was hoped for.** The
  fallback waits for the port and says whether the server answered, died or
  timed out.

## Develop

```bash
pip install -e ".[test]"
python -m pytest
```

The tests run the real boot sequence against a fake server
(`tests/fake_streamlit.py`) and stand-in Tk widgets, so they need no display and
no Streamlit, and finish in seconds. `tests/test_rules.py` also holds the
package to its own rules: standard library only, ASCII only, a docstring on
every definition.

A release bumps `quietlaunch.__version__` (the one place the version is
written; `pyproject.toml` reads it), adds a [CHANGELOG](CHANGELOG.md) entry,
and tags `vX.Y.Z`. Consumers pin the tag.

## Licence

MIT. See [LICENSE](LICENSE).
