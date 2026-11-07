"""
Local Nexus Intelligence server.

Serves site/ at http://localhost:8787 and refreshes the news every hour in the
background. POST /api/refresh fetches immediately (used by the Refresh button).

    python local/serve.py            # port 8787
    python local/serve.py 9000       # custom port
"""

from __future__ import annotations

import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_news  # noqa: E402

SITE = Path(__file__).resolve().parent.parent / "site"
REFRESH_SECONDS = 60 * 60
_lock = threading.Lock()
_last_run = 0.0


def refresh(min_gap: float = 60) -> None:
    """Fetch news; skip if another fetch ran in the last `min_gap` seconds."""
    global _last_run
    with _lock:
        if time.time() - _last_run < min_gap:
            return
        try:
            fetch_news.run()
        except Exception as e:
            print(f"refresh failed: {e}", file=sys.stderr)
        _last_run = time.time()


def scheduler() -> None:
    while True:
        refresh(min_gap=0)
        time.sleep(REFRESH_SECONDS)


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/refresh":
            refresh()
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def end_headers(self):
        if self.path.startswith("/data.json"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # keep the console quiet except for errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    threading.Thread(target=scheduler, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(SITE)))
    print(f"Nexus Intelligence running at http://localhost:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
