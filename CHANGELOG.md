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
  POSIX terminated the one pid, never noticed because the launcher had only run
  on Windows.
- **A failed install shows pip's last lines**, not only the log's path, and a
  missing app or Streamlit is named in the window.
- **Usage errors under `pythonw` raise a message box**, as argparse's stderr is
  None there.

Tests: the boot sequence, port choice, marker rules and the no-tkinter fallback,
against a fake server and stand-in widgets; each historical Windows trap is
planted in a copy of the module and shown to fail its test.
