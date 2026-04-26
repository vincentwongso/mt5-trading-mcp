"""AuditLog — JSONL append-only with size-based rotation."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from mt5_mcp.policy.audit import AuditLog


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=1024)
    yield a
    a.close()


def test_writes_one_jsonl_line_per_event(audit: AuditLog, tmp_path: Path):
    audit.write({"tool": "place_order", "action": "executed", "ticket": 42})
    audit.write({"tool": "get_positions", "action": "called"})
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ticket"] == 42
    assert json.loads(lines[1])["action"] == "called"


def test_event_includes_iso_utc_timestamp(audit: AuditLog, tmp_path: Path):
    audit.write({"tool": "ping", "action": "called"})
    line = (tmp_path / "audit.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert "ts" in rec
    assert rec["ts"].endswith("Z") or rec["ts"].endswith("+00:00")


def test_rotates_when_size_exceeds_max_bytes(tmp_path: Path):
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=200)
    for i in range(20):
        a.write({"tool": "x", "action": "called", "i": i, "padding": "abcdefghij" * 3})
    a.close()

    files = sorted(tmp_path.iterdir())
    rotated = [f for f in files if f.name.startswith("audit.jsonl.")]
    assert len(rotated) >= 1, f"expected rotation, found: {[f.name for f in files]}"
    current = (tmp_path / "audit.jsonl").read_text().splitlines()
    rotated_lines = sum(len(f.read_text().splitlines()) for f in rotated)
    assert len(current) + rotated_lines == 20


def test_concurrent_writers_serialise_correctly(tmp_path: Path):
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=1_000_000)
    n_threads = 8
    n_per = 50

    def worker(worker_id: int):
        for i in range(n_per):
            a.write({"tool": "x", "action": "called", "wid": worker_id, "i": i})

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    a.close()

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == n_threads * n_per
    for ln in lines:
        json.loads(ln)


def test_concurrent_writes_preserve_file_order_with_timestamps(tmp_path: Path):
    """Under concurrent load, the in-lock `ts` generation guarantees that
    file order matches timestamp order (no apparent time regressions)."""
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=1_000_000)
    n_threads = 4
    n_per = 100

    def worker(wid: int):
        for i in range(n_per):
            a.write({"tool": "x", "action": "called", "wid": wid, "i": i})

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    a.close()

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == n_threads * n_per
    timestamps = [json.loads(ln)["ts"] for ln in lines]
    # File order must match timestamp order. Equal timestamps allowed
    # (sub-second resolution); strictly decreasing timestamps would mean
    # `ts` was generated outside the lock.
    for prev, curr in zip(timestamps, timestamps[1:]):
        assert prev <= curr, f"out-of-order ts: {prev!r} then {curr!r}"
