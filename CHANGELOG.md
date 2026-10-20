# Changelog

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
