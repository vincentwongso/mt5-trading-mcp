"""SQLite-backed idempotency cache for mutating-tool replays.

Schema: one row per (key, action) pair. Lookups are scoped by action so
the same key can be re-used across different tool kinds without colliding.
Same-key-same-hash → replay; same-key-different-hash → divergent (caller bug).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal


logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency (
    key             TEXT NOT NULL,
    action          TEXT NOT NULL,
    request_hash    TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    PRIMARY KEY (key, action)
);
"""


LookupResult = tuple[Literal["hit", "diverged"], str | None]


class IdempotencyStore:
    def __init__(self, *, path: Path | str, ttl_seconds: int) -> None:
        self._path = Path(path)
        self._ttl = int(ttl_seconds)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def lookup(
        self, *, key: str | None, action: str, request_hash: str
    ) -> LookupResult | None:
        """Return ('hit', result_json) on replay, ('diverged', None) on key
        collision, or None if no cache entry exists.

        Evicts expired rows for the (key, action) pair in-band.
        """
        if key is None:
            return None
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "SELECT request_hash, result_json, expires_at "
                "FROM idempotency WHERE key = ? AND action = ?",
                (key, action),
            )
            row = cur.fetchone()
            if row is None:
                return None
            stored_hash, result_json, expires_at = row
            if expires_at <= now:
                self._conn.execute(
                    "DELETE FROM idempotency WHERE key = ? AND action = ?",
                    (key, action),
                )
                self._conn.commit()
                return None
            if stored_hash == request_hash:
                return ("hit", result_json)
            return ("diverged", None)

    def put(
        self,
        *,
        key: str | None,
        action: str,
        request_hash: str,
        result_json: str,
    ) -> None:
        """Cache `result_json` under (key, action). No-op if key is None.

        First-write-wins: if an unexpired entry exists for the (key, action)
        pair, this method is a no-op. The reasoning: a divergent put would
        silently destroy the original cached result, breaking the replay
        guarantee for any concurrent agent still holding the old idempotency_key.
        """
        if key is None:
            return
        now = int(time.time())
        expires_at = now + self._ttl
        with self._lock:
            cur = self._conn.execute(
                "SELECT request_hash, expires_at FROM idempotency "
                "WHERE key = ? AND action = ?",
                (key, action),
            )
            row = cur.fetchone()
            if row is not None:
                stored_hash, stored_exp = row
                if stored_exp > now:
                    # Unexpired entry already cached — first-write-wins.
                    if stored_hash != request_hash:
                        logger.warning(
                            "idempotency.put: ignoring divergent hash for key=%r "
                            "action=%r (existing entry has different request_hash)",
                            key, action,
                        )
                    return
                # Expired — fall through and overwrite below.
            self._conn.execute(
                "INSERT INTO idempotency "
                "(key, action, request_hash, result_json, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key, action) DO UPDATE SET "
                "request_hash = excluded.request_hash, "
                "result_json = excluded.result_json, "
                "created_at = excluded.created_at, "
                "expires_at = excluded.expires_at",
                (key, action, request_hash, result_json, now, expires_at),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass  # already closed
