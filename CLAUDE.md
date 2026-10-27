# CLAUDE.md: working in this repo

quietlaunch is one module, `quietlaunch/launcher.py`, and its tests. Most of
its code is a Windows trap with its reason beside it; README's "Why it looks
the way it does" is the list. Rules:

- **Standard library only, ASCII only, a docstring on every definition.**
  `tests/test_rules.py` enforces all three, through `samebytes.source` (a
  test extra). The supervisor is the one process that must not fail, so it
  imports nothing it could lack.
- **Never import the app.** It spawns `streamlit run <app>` and watches a
  socket; putting the app's imports inside the supervisor is the failure this
  design exists to avoid.
- **Do not "simplify" these**, each of which was a real bug: `SO_REUSEADDR` in
  `_port_is_free` (inverted on Windows); asking `_port_is_free` before
  `_port_answers`; any reuse test with fewer than marker, live pid and health;
  a widget touched from the boot thread; the lock or the post-`mainloop`
  join around the Popen hand-over; killing only the spawned pid; using
  `sys.executable` instead of `_console_python()` for a child.
- **A new trap gets a planted test.** Re-introduce the bug in a copy of the
  module and show its test fails before trusting the test's pass.
- **The version is written once**, `quietlaunch.__version__`; `pyproject.toml`
  reads it. A release bumps it, adds a CHANGELOG entry, and tags `vX.Y.Z`.
  Consumers pin the tag (economicspace: `requirements-ui.txt`, and its
  `launch_ui.py` shim compares the tag to the installed version).
- The tree lives in OneDrive. `*-DESKTOP-*` files are sync-conflict copies:
  diff, then delete; never commit one. Never `git stash`. `.githooks/` is
  samebytes' stat-cache hook (opt in with `git config core.hooksPath
  .githooks`); CI's `hooks` job holds the copies to the samebytes tag the test
  extra pins, and `tests/test_rules.py` holds every git pin to one ref.
