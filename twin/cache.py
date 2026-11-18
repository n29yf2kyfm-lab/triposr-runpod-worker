"""A disk cache with the rate limit built in, not bolted on.

Nominatim's and Overpass's terms both cap request rate and both
explicitly encourage caching. Those are not two separate concerns: the
cache is HOW the rate limit is respected, because the request that never
leaves is the one that cannot breach a policy. So the throttle lives
here, on the miss path, rather than in each provider where one forgotten
call would break the whole promise.

SQLite rather than Redis because this must run on a laptop, in CI, and
in a container with nothing installed. Cache entries record which
licence the payload arrived under, so a source whose terms forbid
caching cannot be cached by accident — `put` refuses it.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time

from . import licences

DEFAULT_PATH = os.environ.get(
    "TWIN_CACHE", os.path.join(os.path.expanduser("~"), ".twin", "cache.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  key TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  licence TEXT NOT NULL,
  payload TEXT NOT NULL,
  fetched_at REAL NOT NULL,
  ttl REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider ON entries(provider);
"""


class Cache:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(_SCHEMA)
        # Per-provider last-request clock, for the throttle.
        self._last = {}
        self._lock = threading.Lock()

    def _conn(self):
        # One connection per thread: sqlite3 objects are not shareable and
        # the API server is threaded.
        if getattr(self._local, "conn", None) is None:
            self._local.conn = sqlite3.connect(self.path, timeout=10)
        return self._local.conn

    @staticmethod
    def key(provider: str, *parts) -> str:
        raw = provider + "|" + "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, key: str):
        cur = self._conn().execute(
            "SELECT payload, fetched_at, ttl FROM entries WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        payload, fetched, ttl = row
        if ttl > 0 and time.time() - fetched > ttl:
            return None
        return json.loads(payload)

    def put(self, key: str, provider: str, licence_key: str, payload,
            ttl: float = 7 * 86400):
        # A licence that forbids caching must not be cached — checking it
        # here means no provider can leak past the rule by forgetting.
        if licences.check(licence_key, licences.USE_CACHE, raises=False):
            return False
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?)",
                (key, provider, licence_key, json.dumps(payload),
                 time.time(), ttl))
        return True

    def throttle(self, provider: str, min_interval: float):
        """Block until this provider may be called again.

        Crude and correct. The public endpoints ask for one request per
        second; sleeping the difference is exactly that, and it costs
        nothing on the cache-hit path because callers only reach here on
        a miss.
        """
        if min_interval <= 0:
            return
        with self._lock:
            last = self._last.get(provider, 0.0)
            wait = min_interval - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            self._last[provider] = time.time()

    def stats(self) -> dict:
        cur = self._conn().execute(
            "SELECT provider, COUNT(*) FROM entries GROUP BY provider")
        return {"entries": dict(cur.fetchall()), "path": self.path}


_default = None


def default() -> Cache:
    global _default
    if _default is None:
        _default = Cache()
    return _default
