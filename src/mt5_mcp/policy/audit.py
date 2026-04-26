"""Append-only JSONL audit log with size-based rotation.

One file handle per process; an RLock guards the write+rotate transition.
Rotation renames the current file to `audit.jsonl.<unix_epoch>` and opens
a fresh handle. No compression — operators rotate or archive manually.
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
        rotated = self._path.with_name(f"{self._path.name}.{int(time.time())}")
        # If two writes race past the size check before either rotates, the
        # second rename target may already exist — fall back to a counter.
        suffix = 0
        candidate = rotated
        while candidate.exists():
            suffix += 1
            candidate = self._path.with_name(f"{self._path.name}.{int(time.time())}.{suffix}")
        os.replace(self._path, candidate)
        logger.info("audit log rotated: %s -> %s", self._path, candidate)
        self._open()

    def write(self, event: dict[str, Any]) -> None:
        """Append one JSONL event. A 'ts' field is added automatically."""
        record = {"ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                  **event}
        line = json.dumps(record, separators=(",", ":"), default=str)
        with self._lock:
            if self._fp is None:
                self._open()
            self._fp.write(line + "\n")
            self._rotate_if_needed()

    def close(self) -> None:
        with self._lock:
            self._close_handle()
