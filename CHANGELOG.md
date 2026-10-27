# Changelog

## Unreleased

- **`--version`** prints `quietlaunch X.Y.Z`, read from
  `quietlaunch.__version__`.
- README names each option's command-line flag beside its `LaunchConfig`
  field, and the docs describe what happens rather than how much it matters.
- Tests pick ports below every OS's ephemeral range, so they pass on macOS,
  and the fake server listens without a reverse-DNS lookup.
- `.githooks/` carries samebytes' stat-cache hook for working copies in a
  synced folder; CI's `hooks` job checks the copies against the samebytes tag.
- CI runs `actions/checkout@v5` and `actions/setup-python@v6`, which run on
  Node 24; the v4 and v5 they replace targeted the deprecated Node 20.
- Package metadata lists each supported Python version and macOS, and links
  the issue tracker and this changelog.
- `tests/test_rules.py` runs its rules through `samebytes.source` (v0.3.0, a
  test extra), the copy the family shares. The import rule now answers on
  Python 3.9 instead of skipping there, and async definitions need a
  docstring too.
- samebytes v0.5.0 in the test extra and in CI's `hooks` job, which had sat on
  v0.1.0; `tests/test_rules.py` holds every git pin to one ref and every
  `LaunchConfig` field to a help comment. `port_tries` gets its own: the
  comment above it was written for `port_first` and reached only that field.

## v0.1.0 (2026-10-20)

First release: economicspace's `launch_ui.py` (as of economicspace d9c6093),
made into a package. The seven commits that built it are replayed at the start
of this repository's history, limited to that file.

What changed in moving it:

- **Configurable.** The app path, window text, boot hint, working directory,
  state directory, ports, boot timeout, install source and extra `streamlit run`
  arguments were constants or literals; they are `LaunchConfig` fields, with a
  `python -m quietlaunch` command line over them and a windowless
  `quietlaunch` GUI script.
- **The marker is per app** (`running-<app>.json`, recording the app path).
  economicspace's single `running.json` was safe only because one app used the
  folder; two apps sharing a state directory could adopt, or delete the note
  of, each other's server.
- **POSIX stops the whole process tree.** The server starts in its own session
  and the group is killed. Before, only Windows killed children (`taskkill /T`);
  POSIX terminated the one pid, which went unnoticed because the launcher had
  only ever run on Windows.
- **A busy dashboard is reused, not duplicated.** The reuse health check
  waited 1 s; economicspace's dashboard took 4.4 s to answer during a page
  load, so a second double-click then booted a second server on the next port.
  Found while verifying this release; launch_ui.py has the same bug. It now
  waits up to 15 s once the marker and a live pid agree.
- **A failed install shows pip's last lines**, not only the log's path, and a
  missing app or Streamlit is named in the window.
- **Usage errors under `pythonw` show a message box**, since argparse's stderr
  is None there.

Tests: the boot sequence, port choice, marker rules and the no-tkinter fallback,
against a fake server and stand-in widgets; each historical Windows trap is
planted in a copy of the module and shown to fail its test.
