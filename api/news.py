"""
Vercel serverless function: GET /api/news

Returns the same JSON as site/data.json, but freshly fetched. Vercel's CDN caches the
response (s-maxage) and refreshes it in the background (stale-while-revalidate), so
the feeds are fetched at most every CACHE_SECONDS no matter how many people visit,
and the site stays current without any scheduler.

History: each response merges the live feeds with the data.json baked into the last
deployment (31 days of stories). If the env var DEPLOY_HOOK is set to a Vercel deploy
hook URL, the function also triggers a rebuild when that baked copy is over
REBUILD_AFTER old, so the history keeps growing even if GitHub's cron stalls.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "local"))
import fetch_news  # noqa: E402

CACHE_SECONDS = 15 * 60
REBUILD_AFTER = 3 * 3600
_memo: dict = {"at": 0.0, "body": b""}
_lock = threading.Lock()
_last_hook = 0.0


def _get(url: str, timeout: float = 10) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": fetch_news.UA}), timeout=timeout) as r:
        return r.read()


def baked_data() -> dict:
    """The data.json published with the current production deployment."""
    host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL")
    if not host:
        return {}
    try:
        return json.loads(_get(f"https://{host}/data.json?fn={int(time.time())}"))
    except Exception as e:  # first deploy, network hiccup…
        print(f"baked data.json unavailable: {e}", file=sys.stderr)
        return {}


def maybe_rebuild(baked: dict) -> None:
    global _last_hook
    hook = os.environ.get("DEPLOY_HOOK", "").strip()
    gen = baked.get("generated_at")
    if not hook or not gen or time.time() - _last_hook < 3600:
        return
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(gen)).total_seconds()
    if age < REBUILD_AFTER:
        return
    _last_hook = time.time()
    try:
        urlopen(Request(hook, method="POST"), timeout=10).read()
        print(f"baked data {age / 3600:.1f}h old, triggered rebuild")
    except Exception as e:
        print(f"deploy hook failed: {e}", file=sys.stderr)


def fresh_body() -> bytes:
    with _lock:  # one fetch per warm instance at a time
        if time.time() - _memo["at"] < CACHE_SECONDS and _memo["body"]:
            return _memo["body"]
        baked = baked_data()
        maybe_rebuild(baked)
        out, _ = fetch_news.build(baked.get("articles", []), timeout=8)
        if not any(s["ok"] for s in out["sources"]) and baked.get("articles"):
            out = baked  # every feed failed (outbound network down?): serve the baked copy
        out["live"] = out is not baked
        _memo.update(at=time.time(), body=json.dumps(out, ensure_ascii=False).encode())
        return _memo["body"]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, status = fresh_body(), 200
            cache = f"public, max-age=0, s-maxage={CACHE_SECONDS}, stale-while-revalidate=86400"
        except Exception as e:
            body, status = json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), 500
            cache = "no-store"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
