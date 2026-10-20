# -*- coding: utf-8 -*-
"""A stand-in for `streamlit run`, so the boot sequence can be tested in seconds.

    python fake_streamlit.py PORT serve   answer /_stcore/health with `ok`
    python fake_streamlit.py PORT slow    the same, 3 s late, like a busy app
    python fake_streamlit.py PORT parent  a child serves; this one only waits
    python fake_streamlit.py PORT die     print a traceback-shaped line, exit 3
    python fake_streamlit.py PORT hang    never listen, never exit
"""

import http.server
import sys
import time


class _Health(http.server.BaseHTTPRequestHandler):
    """Streamlit's health endpoint and nothing else."""

    # Seconds the health answer takes: a server whose app is busy (`slow`).
    delay = 0.0

    def do_GET(self):
        """`ok` on the health path, 404 anywhere else."""
        if self.path == "/_stcore/health":
            time.sleep(self.delay)
            body = b"ok"
            self.send_response(200)
        else:
            body = b"not here"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Quiet: the launcher's log should hold only what a test plants."""


def main():
    """Run in the mode named on the command line."""
    port, mode = int(sys.argv[1]), sys.argv[2]
    if mode in ("serve", "slow"):
        if mode == "slow":
            _Health.delay = 3.0
        print("fake streamlit serving on %d" % port, flush=True)
        http.server.HTTPServer(("127.0.0.1", port), _Health).serve_forever()
    elif mode == "parent":
        # Streamlit's shape: the process the launcher spawned is not the only
        # one. The child serves; this one only waits, so killing just this pid
        # leaves the port held.
        import subprocess
        child = subprocess.Popen([sys.executable, __file__, str(port), "serve"])
        print("child pid %d" % child.pid, flush=True)
        child.wait()
    elif mode == "die":
        print("ModuleNotFoundError: No module named 'planted_failure'",
              flush=True)
        sys.exit(3)
    elif mode == "hang":
        while True:
            time.sleep(1)
    else:
        sys.exit("unknown mode %r" % mode)


if __name__ == "__main__":
    main()
