"""Append-only JSONL audit log with size-based rotation.

One file handle per process; an RLock guards both `write()` and rotation
so the file remains consistent under concurrent FastMCP request threads.
The `ts` field is generated inside the lock so file order matches wall
clock order — important for operators reconstructing event sequences.

Durability trade-offs (acceptable for a local-first developer tool):
- Line-buffered mode means each `\\n`-terminated write reaches the OS,
  but `close()` does NOT call `os.fsync`. Events in the OS page cache
  are lost on power failure. We accept this risk because the MCP runs
  on the customer's local machine and the audit log volume is low.
- `json.dumps(..., default=str)` silently stringifies non-serialisable
  values (Decimal, datetime, etc.). The expected callers (PolicyEngine
  in Task 11) construct explicit primitive dicts; if a complex object
  ever leaks through, it appears in the log as its repr rather than
  raising. Acceptable for this phase; revisit if the audit log gains
  programmatic consumers.

Rotation renames the current file to `audit.jsonl.<unix_epoch>` (with a
`.<suffix>` counter for same-second collisions) and opens a fresh handle.
No compression — operators rotate or archive manually.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, *, path: Path | str, max_bytes: int) -> None:
        self._path = Path(path)
        self._max_bytes = int(max_bytes)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp: io.TextIOWrapper | None = None
        self._open()

    def _open(self) -> None:
        # Line-buffered text mode so each write is flushed without an
        # explicit .flush() call. UTF-8 on every platform.
        self._fp = open(self._path, "a", encoding="utf-8", buffering=1)

    def _close_handle(self) -> None:
        if self._fp is not None:
            try:
                self._fp.close()
            finally:
                self._fp = None

    def _rotate_if_needed(self) -> None:
        try:
            size = os.path.getsize(self._path)
        except FileNotFoundError:
            return
        if size < self._max_bytes:
            return
        self._close_handle()
        epoch = int(time.time())
        rotated = self._path.with_name(f"{self._path.name}.{epoch}")
        suffix = 0
        candidate = rotated
        while candidate.exists():
            suffix += 1
            candidate = self._path.with_name(f"{self._path.name}.{epoch}.{suffix}")
        os.replace(self._path, candidate)
        logger.info("audit log rotated: %s -> %s", self._path, candidate)
        self._open()

    def write(self, event: dict[str, Any]) -> None:
        """Append one JSONL event. A 'ts' field is added inside the lock so
        file order matches wall-clock order under concurrent writers."""
        with self._lock:
            if self._fp is None:
                self._open()
            ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            record = {"ts": ts, **event}
            line = json.dumps(record, separators=(",", ":"), default=str)
            self._fp.write(line + "\n")
            self._rotate_if_needed()

    def close(self) -> None:
        with self._lock:
            self._close_handle()
