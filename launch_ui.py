# -*- coding: utf-8 -*-
"""Start the dashboard with no terminal window, and give it something to close.

    pyw -3 launch_ui.py          (what Dashboard.vbs runs)
    py  -3 launch_ui.py          (same thing, with a console to watch)

WHY THIS EXISTS. `run.bat ui` USED TO run `streamlit run ui.py` in the
foreground, so the console window WAS the app: closing it stopped the server,
and it had to stay open and in the way for as long as the dashboard was up.
That is the terminal this file removes. `run.bat ui` now hands off to
Dashboard.vbs, which runs this, and falls back to the foreground server only
when Dashboard.vbs is missing.

Removing it costs more than hiding it, which is the whole design here. A
`pythonw` process with no console has no window to close and no output to read,
so a failed start is a program that silently does not appear, and a successful
one is a server nobody can stop without Task Manager. So this launcher puts up
a small control window instead: it says what is happening while Streamlit boots,
opens the browser once the port actually answers, and stops the server when it
is closed. The window replaces the console rather than merely suppressing it.

NOT A SECOND ENTRY POINT TO THE MODEL. It never imports master, ui, or anything
under modules/ -- it spawns `streamlit run ui.py` as a child and watches a
socket. That is deliberate: this process is the one thing that must not fail,
and importing the pipeline here would put a 1 MB module and a multiprocessing
pool inside the supervisor. It also sidesteps `_spawn_environment` entirely,
since nothing here is ever a worker's `__main__`.

ASCII ONLY, like the rest of the pipeline's output. Nothing here is printed to
a redirected stdout, but the rule is cheap to keep and the log file this writes
is read by the same eyes.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "ui.py")
LOG_DIR = os.path.join(HERE, ".launcher")

# Per PORT, not one shared file: two launchers on different ports would both
# truncate a single dashboard.log, and the surviving copy would be the wrong
# one exactly when somebody is trying to read it to find out why the other
# failed.
def _log_path(port):
    return os.path.join(LOG_DIR, "dashboard-%d.log" % port)


# Names the server THIS launcher started, so a later launch can tell our
# dashboard from any other Streamlit app that happens to hold the port.
MARKER = os.path.join(LOG_DIR, "running.json")

# Streamlit's default, then upwards. A second launch lands on the next free one
# rather than fighting the first.
PORT_FIRST = 8501
PORT_TRIES = 12

# Cold start imports master.py, which is ~1 MB and pulls pandas, numpy and
# yfinance behind it. On a Drive File Stream working copy that read is slow and
# serialises, so this is minutes rather than seconds the first time.
BOOT_TIMEOUT_S = 300.0

# How long main() waits for the boot thread to stand down before exiting. Only
# ever reached when the window is closed mid-boot; see Launcher.finish.
JOIN_TIMEOUT_S = 15.0

# How often the main thread drains the worker's queue. Fast enough that status
# lines look immediate, slow enough to be free.
POLL_MS = 80

# CREATE_NO_WINDOW. The child is a console program; without this it opens the
# very window this file exists to remove.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------
# Talking to the user without a console
# --------------------------------------------------------------------------

def _message_box(title, text):
    """Last-resort dialog, for failures that happen before tkinter is up."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    # A console may not exist. If it does, this is better than nothing.
    try:
        sys.stderr.write(title + "\n\n" + text + "\n")
    except Exception:
        pass


def _console_python():
    """The console interpreter beside whatever is running this.

    Under `pyw`, sys.executable is pythonw.exe, whose stdout is None. Streamlit
    writes to stdout on startup and its own child processes inherit those
    handles, so launching it from pythonw is a way to find out which libraries
    handle a None stdout badly. Hand the child a real python.exe and redirect it
    to a file instead -- then the log below is a real log.
    """
    exe = sys.executable or ""
    base = os.path.basename(exe).lower()
    if base.startswith("pythonw"):
        cand = os.path.join(os.path.dirname(exe),
                            os.path.basename(exe).replace("pythonw", "python", 1))
        if os.path.isfile(cand):
            return cand
    return exe


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------

def _port_is_free(port):
    """Can we actually take this port?

    Deliberately no SO_REUSEADDR. On Unix that option means "reuse a port stuck
    in TIME_WAIT"; on WINDOWS it means "bind even though someone else already
    has it", so setting it made this return True for a port Streamlit was
    serving at that moment -- which sent the caller off to start a second
    server on an occupied port. Whether a port is taken is answered by
    _port_answers; this only confirms we can bind the one nobody holds.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _port_answers(port, timeout=0.4):
    """True if something is LISTENING on this localhost port.

    The other half of `_port_is_free`, and the two are deliberately separate
    questions asked in that order. `_port_is_free` does a bare `bind` and must
    NOT set SO_REUSEADDR: on Windows that flag is inverted, meaning "bind even
    though someone else holds it" rather than Unix's "reuse a TIME_WAIT port",
    so setting it made a free-port probe answer True for the very port
    Streamlit was serving on at that moment.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _is_streamlit_server(port):
    """True if something on this port is a live Streamlit server -- ANY of them.

    `/_stcore/health` answers `ok` and has since Streamlit 1.19; anything else
    on the port fails the request or answers something else. Note what this
    canNOT tell you: whether the app being served is ours. That is the marker
    file's job, and conflating the two is how a double-click would have opened
    somebody else's Streamlit project because it got to 8501 first.
    """
    import urllib.request
    try:
        url = "http://127.0.0.1:%d/_stcore/health" % port
        with urllib.request.urlopen(url, timeout=1.0) as r:
            return r.read(32).strip().lower() == b"ok"
    except Exception:
        return False


def _write_marker(port, pid):
    """Record the port and pid of the server WE started, under .launcher/.

    `_is_streamlit_server` can tell you a Streamlit is on the port; only this
    can tell you it is ours. Reuse needs the marker, a live pid AND a healthy
    port, so a crashed launcher, a recycled pid and a stranger's app each fail a
    different one of the three. Failing to write it is not fatal: a launcher
    that cannot leave a note still runs the dashboard.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(MARKER, "w", encoding="utf-8") as f:
            json.dump({"port": port, "pid": pid, "started": time.time()}, f)
    except (OSError, TypeError, ValueError):
        pass                       # a launcher that cannot write a note still works


def _read_marker():
    """(port, pid) from the marker file, or (None, None) if it is absent or bad.

    Deliberately swallows everything: the marker is a hint left by a previous
    process, so a truncated or hand-edited one means "no usable server", never
    an error the user has to deal with.
    """
    try:
        with open(MARKER, encoding="utf-8") as f:
            d = json.load(f)
        return int(d["port"]), int(d["pid"])
    except Exception:
        return None, None


def _clear_marker():
    """Delete the marker once the server it names is gone. A missing file is fine."""
    try:
        os.remove(MARKER)
    except OSError:
        pass


def _pid_alive(pid):
    """True if the process still exists, without signalling it.

    POSIX gets `kill(pid, 0)`. Windows has no such call, so this opens the
    process with QUERY_LIMITED_INFORMATION and reads its exit code:
    STILL_ACTIVE (259) means alive. That constant is genuinely ambiguous in
    Win32, since a process may exit WITH code 259, but nothing here exits with
    a code at all, and the alternative, a full snapshot walk, costs far more
    for the same answer.
    """
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)     # QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wt.DWORD()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def _choose_port():
    """(port, already_running). Reuses a dashboard that is already up.

    Listening is tested before bindability, not after: "is something there" is
    a question about the network, and only once nothing is there does it matter
    whether we could bind. Written the other way round it depends on bind
    semantics to detect a live server, which is what the SO_REUSEADDR note
    above is about.
    """
    port, pid = _read_marker()
    if (port and pid and _pid_alive(pid) and _port_answers(port)
            and _is_streamlit_server(port)):
        return port, True                   # our own dashboard, still up

    # All three conditions matter. The pid check rejects a marker left behind
    # by a crash; the health check rejects a pid that Windows has recycled onto
    # some unrelated process; and reaching here at all means we will not adopt
    # a Streamlit server we did not start.
    _clear_marker()
    for port in range(PORT_FIRST, PORT_FIRST + PORT_TRIES):
        if _port_answers(port):
            continue                        # somebody is there; do not disturb
        if _port_is_free(port):
            return port, False
    return PORT_FIRST, False


# --------------------------------------------------------------------------
# The child process
# --------------------------------------------------------------------------

def _tail(path, lines=14):
    """Last few lines of a log file for the failure message, or "" if unreadable.

    Under `pythonw` there is no console, so this text IS the error report; a
    boot failure that could not say why is the whole reason the launcher grew a
    window rather than merely hiding the console.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            got = f.read().splitlines()
    except OSError:
        return ""
    return "\n".join(got[-lines:]).strip()


def _start_streamlit(port):
    """Spawn the server. Returns (Popen, logfile_handle)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log = open(_log_path(port), "w", encoding="utf-8", errors="replace")
    cmd = [
        _console_python(), "-m", "streamlit", "run", APP,
        # headless keeps Streamlit from opening its own browser -- this file
        # opens it once the port actually answers, which is a different moment
        # -- and suppresses the first-run email prompt, which would otherwise
        # sit unanswered on a stdin nobody can reach.
        "--server.headless=true",
        "--server.port=%d" % port,
        "--browser.gatherUsageStats=false",
    ]
    env = dict(os.environ)
    # Same belt and braces as run.bat: the pipeline's own output is ASCII, but
    # tqdm, tracebacks and data values reach this log too.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env, creationflags=_NO_WINDOW,
    )
    return proc, log


def _stop(proc):
    """Kill the server AND its children.

    Streamlit's file watcher and the pipeline's own worker pool are separate
    processes. Terminating only the one we spawned orphans them, and an orphaned
    worker holds the port -- so the next launch finds 8501 busy and not
    answering health, picks 8502, and the stale one lingers until reboot.
    """
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW, timeout=15,
            )
            return
        except Exception:
            pass
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------

def _streamlit_installed():
    """Is Streamlit importable?

    `importlib.util.find_spec` searches the path without importing, so this
    costs microseconds where spawning `python -c "import streamlit"` cost about
    1.5 s -- a third of a warm launch, paid on every single one. It is the same
    interpreter either way: _console_python() is derived from sys.executable,
    so it shares this process's site-packages.

    It answers "installed", not "importable without error". A broken install
    passes here and then fails at spawn -- where the log tail reports the real
    ImportError, which is a better message than this function could produce.
    """
    try:
        import importlib.util
        return importlib.util.find_spec("streamlit") is not None
    except Exception:
        return False


def _pip_install_streamlit():
    """One-time `pip install` of the UI requirements. True if it succeeded.

    Runs through `_console_python()` rather than `sys.executable`, because under
    `pythonw` the latter is the windowless interpreter; output goes to
    `.launcher/install.log`, which `_tail` reads back if this fails.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    req = os.path.join(HERE, "requirements-ui.txt")
    args = ["-r", req] if os.path.isfile(req) else ["streamlit>=1.30"]
    with open(os.path.join(LOG_DIR, "install.log"), "w",
              encoding="utf-8", errors="replace") as log:
        rc = subprocess.run(
            [_console_python(), "-m", "pip", "install"] + args,
            cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        ).returncode
    return rc == 0


# --------------------------------------------------------------------------
# The control window
# --------------------------------------------------------------------------

class Launcher(object):
    """A window that boots the dashboard, then stands in for the console.

    Built and shown BEFORE anything slow happens, so a cold start looks like a
    program starting rather than a double-click that did nothing. Everything
    slow runs on a worker thread and reports back through `_say`; tkinter is
    not thread-safe, so the worker never touches a widget directly.
    """

    def __init__(self, root, tk, ttk):
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.work = queue.Queue()
        # Guards the (proc, logfile, stopping) trio ONLY. Held for the moment
        # it takes to hand the child over, never across _stop -- taskkill can
        # take seconds and the worker must not block on it.
        self.lock = threading.Lock()
        self.proc = None
        self.logfile = None
        self.log_path = None
        self.thread = None
        self.port = None
        self.url = ""
        self.ready = False
        self.finished = False       # boot sequence has reported, pass or fail
        self.stopping = False
        self.pump_id = None

        root.title("Asteroid Pipeline")
        root.geometry("470x230")
        root.minsize(470, 230)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Asteroid mining profitability pipeline",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Dashboard",
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 12))

        self.status = ttk.Label(frame, text="Starting...", font=("Segoe UI", 9),
                                wraplength=420, justify="left")
        self.status.pack(anchor="w")

        self.detail = ttk.Label(frame, text="", font=("Consolas", 8),
                                foreground="#666666", wraplength=420,
                                justify="left")
        self.detail.pack(anchor="w", pady=(4, 0))

        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=420)
        self.bar.pack(anchor="w", pady=(12, 0))
        self.bar.start(12)

        buttons = ttk.Frame(frame)
        buttons.pack(side="bottom", anchor="w", pady=(16, 0))
        self.open_btn = ttk.Button(buttons, text="Open dashboard",
                                   command=self.open_browser, state="disabled")
        self.open_btn.pack(side="left")
        ttk.Button(buttons, text="Stop and quit",
                   command=self.quit).pack(side="left", padx=(8, 0))

        self.pump_id = self.root.after(POLL_MS, self._pump)

    # -- thread-safe reporting ---------------------------------------------
    #
    # The worker thread NEVER touches tkinter, not even through `after`.
    # `Tk.after` registers a Tcl command, which is not thread-safe, and it
    # raises outright once the main loop has gone -- so a user closing the
    # window during the four seconds Streamlit takes to boot produced
    # `RuntimeError: main thread is not in main loop` from inside the worker,
    # where nothing under pythonw would ever have shown it. Instead the worker
    # posts a callable and the main thread runs it. Queue.put is thread-safe;
    # this is the only channel between the two.

    def _post(self, fn):
        """Queue a callable for the MAIN thread. The only worker-to-UI channel."""
        self.work.put(fn)

    def _pump_once(self):
        """Drain the queue on the main thread without rescheduling."""
        while True:
            try:
                fn = self.work.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                pass

    def _pump(self):
        """Drain the queue on the main thread, then reschedule itself.

        `_pump_once` is the same drain without the reschedule, for teardown. An
        exception from a queued callable is swallowed on purpose: a widget
        destroyed between post and run must not stop the pump, which is the only
        way anything reaches the window.
        """
        while True:
            try:
                fn = self.work.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass                      # a dead widget must not stop the pump
        if not self.stopping:
            try:
                self.pump_id = self.root.after(POLL_MS, self._pump)
            except Exception:
                pass

    def _say(self, text, detail=None):
        """Update the status line, and optionally the detail line, from any thread."""
        def apply():
            self.status.configure(text=text)
            if detail is not None:
                self.detail.configure(text=detail)
        self._post(apply)

    def _done_booting(self, ok, message, detail=""):
        """End the boot sequence: stop the progress bar and report pass or fail.

        Enables "Open in browser" only on success. Called exactly once per boot,
        including from `_boot`'s except arm, because a launcher that dies
        silently is indistinguishable from one still working.
        """
        def apply():
            self.bar.stop()
            self.bar.pack_forget()
            self.finished = True
            self.status.configure(text=message)
            self.detail.configure(text=detail)
            if ok:
                self.ready = True
                self.open_btn.configure(state="normal")
        self._post(apply)

    # -- actions ------------------------------------------------------------
    def open_browser(self):
        if self.url:
            webbrowser.open(self.url)

    def quit(self):
        """Stop the server and tear the window down. Safe to call twice.

        Two things here are not optional. The lock makes the read of
        `(proc, logfile)` atomic against the hand-over in `_boot_inner`, because
        closing the window mid-spawn otherwise found `proc` still None, killed
        nothing, and left a server that nothing on screen could stop. And the
        pending `after` is CANCELLED rather than merely left unscheduled:
        clearing `stopping` stops the pump rescheduling, but the one already in
        flight still fires, into a destroyed interpreter.
        """
        with self.lock:
            if self.stopping:
                return
            self.stopping = True
            proc, logfile = self.proc, self.logfile
        # Cancel the queued pump before tearing the window down. Setting
        # `stopping` only stops it RESCHEDULING; the one already in flight
        # still fires, into a destroyed interpreter, and Tcl prints
        # `invalid command name "..._pump"` -- which under pythonw goes
        # nowhere at all and is exactly the kind of thing that stays broken.
        if self.pump_id is not None:
            try:
                self.root.after_cancel(self.pump_id)
            except Exception:
                pass
            self.pump_id = None
        self._say("Stopping the dashboard...")
        self._pump_once()
        self.root.update_idletasks()
        _stop(proc)
        if proc is not None:
            _clear_marker()
        if logfile is not None:
            try:
                logfile.close()
            except Exception:
                pass
        self.root.destroy()

    # -- the boot sequence, on a worker thread ------------------------------
    def boot(self):
        self.thread = threading.Thread(target=self._boot, daemon=True)
        self.thread.start()

    def finish(self):
        """Called after the main loop ends. The last chance to not leak a server.

        The boot thread is a daemon, so returning from main() kills it wherever
        it happens to be -- and if that is one statement past Popen, the child
        is already alive and nothing has been recorded that could stop it. The
        lock makes the hand-over atomic; this makes sure the hand-over actually
        HAPPENS, by giving the thread a bounded moment to notice `stopping` and
        clean up after itself. Without it the lock protects a window the
        interpreter never lives long enough to reach.

        Bounded, not indefinite: a thread stuck in pip cannot hold the process
        open. That case is safe anyway -- it has not spawned anything yet, so
        being killed leaks nothing.
        """
        if self.thread is not None:
            self.thread.join(timeout=JOIN_TIMEOUT_S)
        with self.lock:
            proc, logfile = self.proc, self.logfile
            self.proc, self.logfile = None, None
        if proc is not None:
            _stop(proc)                     # a no-op if quit() already did it
            _clear_marker()
        if logfile is not None:
            try:
                logfile.close()
            except Exception:
                pass

    def _boot(self):
        """Worker-thread entry point: run the boot sequence, report any exception.

        The bare `except` is the point. This runs on a daemon thread under
        `pythonw`, where an unhandled traceback goes nowhere at all, so every
        failure has to come back through `_done_booting` and onto the window.
        """
        try:
            self._boot_inner()
        except Exception as exc:                       # never die silently
            try:
                self._done_booting(
                    False, "The launcher hit an error.",
                    "%s: %s" % (type(exc).__name__, exc))
            except Exception:
                pass          # reporting a failure must not raise a second one

    def _boot_inner(self):
        """Install if needed, pick a port, adopt or spawn a server, wait for health.

        Checks `self.stopping` between every slow step, because the window can be
        closed at any point during the seconds this takes and everything past
        that point is work nobody is waiting for. If it finds OUR server already
        running it reopens the browser and quits rather than supervising nothing:
        a second control window whose Stop button stops nothing, beside one that
        works, is worse than no window.
        """
        if not os.path.isfile(APP):
            self._done_booting(False, "ui.py is not next to this launcher.",
                               "Looked in: %s" % HERE)
            return

        if not _streamlit_installed():
            self._say("Installing Streamlit (one time, a minute or two)...",
                      "pip install -r requirements-ui.txt")
            if not _pip_install_streamlit():
                self._done_booting(
                    False, "Could not install Streamlit.",
                    "See .launcher/install.log")
                return
        if self.stopping:
            return                  # closed during the install; spawn nothing

        self.port, running = _choose_port()
        self.url = "http://localhost:%d" % self.port
        if self.stopping:
            return

        if running:
            # Someone double-clicked twice, or left it running. Reopening beats
            # a second copy of a program that loads a 1 MB module.
            #
            # And then this process GOES AWAY. It supervises nothing -- proc is
            # None -- so leaving its window up would put a second "Stop and
            # quit" button on screen that cannot stop anything, next to the one
            # that can. One dashboard, one control window.
            self._done_booting(True, "Already running -- reopening it in your"
                                     " browser.", self.url)
            self._post(self.open_browser)
            self._post(lambda: self.root.after(1600, self.quit))
            return

        self._say("Starting the server on port %d..." % self.port,
                  "First run loads the pipeline, which takes a minute.")

        # THE HAND-OVER, and it has to be atomic against quit().
        #
        # Popen returns with the child already alive. Assigning it afterwards
        # leaves a window -- tens of milliseconds, but reproducible -- in which
        # the user closes the window, quit() finds self.proc still None, kills
        # nothing, and the server is left holding the port with the only thing
        # that could have stopped it now gone. Under the lock, exactly one of
        # the two sides owns the child: if `stopping` is already set we stop
        # what we just started, otherwise quit() is guaranteed to see it.
        proc, logfile = _start_streamlit(self.port)
        with self.lock:
            abandoned = self.stopping
            if not abandoned:
                self.proc, self.logfile = proc, logfile
                self.log_path = _log_path(self.port)
        if abandoned:
            _stop(proc)
            try:
                logfile.close()
            except Exception:
                pass
            return

        log_note = "See %s" % os.path.relpath(self.log_path, HERE)
        deadline = time.time() + BOOT_TIMEOUT_S
        while time.time() < deadline:
            if self.stopping:
                return
            if proc.poll() is not None:
                self._done_booting(
                    False, "The server stopped while starting up.",
                    _tail(self.log_path) or log_note)
                return
            if _port_answers(self.port):
                # Recorded only once the server actually answers, so the marker
                # never advertises a dashboard that is not there yet. It also
                # survives this launcher being killed, which is what lets the
                # next double-click adopt an already-running server instead of
                # starting a second one.
                _write_marker(self.port, proc.pid)
                self._done_booting(True, "The dashboard is running.", self.url)
                self._post(self.open_browser)
                return
            time.sleep(0.25)

        self._done_booting(
            False, "The server did not come up within %d seconds."
                   % int(BOOT_TIMEOUT_S),
            _tail(self.log_path) or log_note)


def main():
    """Put up the control window, boot the dashboard, and own the stop button.

    The tkinter import is the one thing allowed to fail into a lesser mode: with
    no tkinter there is no window, so this starts the server, opens the browser
    and says in a message box that stopping it means Task Manager.

    `app.finish()` runs AFTER `mainloop()` returns, and joining the boot thread
    there is required rather than tidy: the thread is a daemon, so without the
    join the interpreter exits and kills it wherever it stands, and the lock in
    `quit()` would be guarding a hand-over the process never lives long enough
    to reach.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        # No tkinter: fall back to a plain start with a message box, which is
        # worse (nothing to close) but better than doing nothing at all.
        port, running = _choose_port()
        url = "http://localhost:%d" % port
        if not running:
            proc, logfile = _start_streamlit(port)
            for _ in range(int(BOOT_TIMEOUT_S * 4)):
                if _port_answers(port):
                    _write_marker(port, proc.pid)
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
            logfile.close()
        webbrowser.open(url)
        _message_box("Asteroid Pipeline",
                     "The dashboard is at %s\n\n"
                     "tkinter is missing, so there is no control window -- "
                     "stop the server from Task Manager when you are done."
                     % url)
        return 0

    root = tk.Tk()
    try:
        root.iconify()
        root.deiconify()
    except Exception:
        pass
    app = Launcher(root, tk, ttk)
    app.boot()
    root.mainloop()
    app.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
