"""File-bridge to the AgentScreenshot MQL5 EA.

Requests a native MT5 chart screenshot by dropping a request file into the
terminal's sandboxed ``MQL5/Files/agent_screenshot/`` folder, then waits for
the EA to write back a PNG plus a ``.done`` status file. Windows-only in
practice (needs a GUI terminal with the EA attached); the platform guard
lives in the tool layer, not here, so this module stays import-safe and
unit-testable on any OS.

Request line format (UTF-16-LE, single line, '|'-delimited):
    <id>|<symbol>|<timeframe>|<width>|<height>|<template>
Response file ``<id>.done`` contains ``ok`` or ``err:<reason>`` (UTF-16-LE).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ulid import ULID

from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail

_SUBDIR = "agent_screenshot"


def _files_dir(client: Any) -> Path:
    ti = client.call(lambda m: m.terminal_info())
    data_path = getattr(ti, "data_path", None) if ti is not None else None
    if not data_path:
        raise MT5Error(ErrorDetail(
            code="SCREENSHOT_FAILED",
            message="Could not resolve terminal data_path for the screenshot bridge.",
            retryable=True,
            requires_human=False,
        ))
    d = Path(data_path) / "MQL5" / "Files" / _SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sweep_stale(files_dir: Path, ttl_s: float, clock: Callable[[], float]) -> None:
    """Best-effort removal of bridge files orphaned by earlier timeouts.

    A slow EA can write a ``.png``/``.done`` after this call's ``finally``
    cleanup already ran, leaving files that no request will ever collect.
    Anything older than ``ttl_s`` is deleted. The caller must pass a ``ttl_s``
    that is >= the longest in-flight request window (see ``capture_chart``), so
    a concurrent call's still-pending files are never swept out from under it.
    """
    cutoff = clock() - ttl_s
    for p in files_dir.glob("*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def capture_chart(
    client: Any,
    *,
    symbol: str,
    timeframe_name: str,
    width: int,
    height: int,
    template: str | None,
    timeout_s: float,
    poll_interval_s: float = 0.15,
    id_factory: Callable[[], str] = lambda: str(ULID()),
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    stale_ttl_s: float = 300.0,
    wall_clock: Callable[[], float] = time.time,
) -> bytes:
    """Ask the EA to screenshot ``symbol``/``timeframe_name`` and return PNG bytes.

    Writes the request atomically (``.req.tmp`` then rename) so the EA never
    reads a half-written file. Cleans up all bridge files in a ``finally``.
    """
    d = _files_dir(client)
    # Never sweep files younger than any plausible in-flight request. A
    # concurrent call may keep its .req/.done/.png alive for up to its own
    # timeout_s; if the caller sets timeout_s above the stale_ttl_s floor, the
    # floor alone would sweep those still-pending files and spuriously fail the
    # other call. Guard the floor with timeout_s plus a buffer for EA latency.
    effective_ttl = max(stale_ttl_s, timeout_s + 60.0)
    _sweep_stale(d, effective_ttl, wall_clock)
    req_id = id_factory()
    tmp = d / f"{req_id}.req.tmp"
    req = d / f"{req_id}.req"
    done = d / f"{req_id}.done"
    png = d / f"{req_id}.png"

    payload = f"{req_id}|{symbol}|{timeframe_name}|{width}|{height}|{template or ''}"
    try:
        tmp.write_text(payload, encoding="utf-16-le")
        tmp.replace(req)  # atomic publish on the same filesystem

        deadline = monotonic() + timeout_s
        while monotonic() < deadline:
            if done.exists():
                # MQL5 FileWriteString(FILE_UNICODE) prepends a UTF-16 BOM to
                # new files; strip it so "ok"/"err:" compare correctly.
                status = done.read_text(encoding="utf-16-le").lstrip("﻿").strip()
                if status == "ok":
                    if png.exists():
                        return png.read_bytes()
                    # status written just before the PNG is visible; keep polling
                else:
                    reason = status[4:] if status.startswith("err:") else (status or "unknown")
                    raise MT5Error(ErrorDetail(
                        code="SCREENSHOT_FAILED",
                        message=f"EA failed to capture {symbol} {timeframe_name}: {reason}",
                        retryable=True,
                        requires_human=False,
                        details={"symbol": symbol, "timeframe": timeframe_name},
                    ))
            sleep(poll_interval_s)

        raise MT5Error(ErrorDetail(
            code="SCREENSHOT_TIMEOUT",
            message=(
                f"No response from AgentScreenshot EA within {timeout_s:.0f}s. "
                "Is the EA attached to a chart and the terminal running?"
            ),
            retryable=True,
            requires_human=False,
            details={"symbol": symbol, "timeframe": timeframe_name},
        ))
    finally:
        for p in (tmp, req, done, png):
            try:
                p.unlink()
            except OSError:
                pass
