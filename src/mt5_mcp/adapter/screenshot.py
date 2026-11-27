"""File-bridge to the AgentScreenshot MQL5 EA.

Requests a native MT5 chart screenshot by dropping a request file into the
terminal's sandboxed ``MQL5/Files/agent_screenshot/`` folder, then waits for
the EA to write back a PNG plus a ``.done`` status file. Needs a GUI terminal:
Windows with the AgentScreenshot EA attached, or the Linux Docker image, where
it is preinstalled. The platform guard lives in the tool layer, not here, so this module stays import-safe and
unit-testable on any OS.

Request payload (UTF-16-LE). Line 1 is the header; each following line is one
annotation, fixed arity per type, free text (or fibo's levels) always last:
    <id>|<symbol>|<timeframe>|<width>|<height>|<template>|<scale>|<end_time>|<bars>|<price_min>|<price_max>
    A|hline|<price>|<bgr>|<style>|<text>
    A|vline|<epoch>|<bgr>|<style>|<text>
    A|text|<epoch>|<price>|<bgr>|<text>
    A|label|<corner>|<xdist>|<ydist>|<bgr>|<text>
    A|trend|<epoch1>|<price1>|<epoch2>|<price2>|<bgr>|<style>|<text>
    A|fibo|<epoch1>|<price1>|<epoch2>|<price2>|<bgr>|<style>|<ray 0/1>|<levels, comma-separated>
The five viewport fields are omitted entirely when all are unset.
Response file ``<id>.done`` (UTF-16-LE) contains ``ok``, ``ok|<protocol>`` or
``err:<reason>``. An EA that knows fibo answers ``ok|2`` to a request using it
and rejects annotation kinds it does not know; older EAs answer a bare ``ok``
and silently skip them.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from ulid import ULID

from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail

_SUBDIR = "agent_screenshot"
# Kinds every annotation-aware EA (1.5.1+) draws. Any other kind needs an EA
# that answers ok|<protocol>, since older ones skip it and still say "ok".
_LEGACY_KINDS = ("A|hline|", "A|vline|", "A|text|", "A|label|", "A|trend|")
_OK = re.compile(r"ok(\|\d+)?")
# EA rejections a retry cannot fix.
_PERMANENT = ("unsupported annotation", "malformed annotation")


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
    annotation_lines: list[str] | None = None,
    viewport_fields: list[str] | None = None,
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

    header_parts = [
        req_id, symbol, timeframe_name, str(width), str(height), template or "",
    ]
    # serialize_viewport yields either [] (all unset) or exactly five fields.
    # The any() guard also keeps a hand-built all-empty list a no-op, so the
    # "omitted entirely when all are unset" contract above holds regardless of
    # how the list was built.
    if viewport_fields and any(viewport_fields):
        header_parts.extend(viewport_fields)
    header = "|".join(header_parts)
    # Annotations append one line each, joined with CRLF: MQL5's own file
    # writers emit "\r\n" and FileReadString in FILE_TXT mode is not
    # guaranteed to treat a lone "\n" as a line terminator, so a bare "\n"
    # risks the whole payload being read back as one unsplit line. With no
    # annotation lines, join emits no separator at all, so the payload stays
    # byte-identical to the pre-1.5.1 format and an already-deployed .ex5
    # keeps working.
    payload = "\r\n".join([header, *(annotation_lines or [])])
    new_kinds = sorted({ln.split("|")[1] for ln in annotation_lines or []
                        if not ln.startswith(_LEGACY_KINDS)})
    try:
        # newline="" disables Python's own newline translation, so the "\r\n"
        # already in payload reaches disk unmodified. Without it, a Windows
        # Python process would re-translate each embedded "\n" to "\r\n",
        # doubling up to "\r\r\n" and corrupting the payload.
        with open(tmp, "w", encoding="utf-16-le", newline="") as f:
            f.write(payload)
        tmp.replace(req)  # atomic publish on the same filesystem

        deadline = monotonic() + timeout_s
        while monotonic() < deadline:
            if done.exists():
                # MQL5 FileWriteString(FILE_UNICODE) prepends a UTF-16 BOM to
                # new files; strip it so "ok"/"err:" compare correctly.
                status = done.read_text(encoding="utf-16-le").lstrip("﻿").strip()
                if _OK.fullmatch(status):
                    if new_kinds and status == "ok":
                        raise MT5Error(ErrorDetail(
                            code="SCREENSHOT_FAILED",
                            message=(
                                "The AgentScreenshot EA in the terminal is too old to "
                                f"draw {', '.join(new_kinds)} annotations and captured "
                                "the chart without them. Re-copy or recompile "
                                "AgentScreenshot.ex5 (see mql5/README.md), then retry."
                            ),
                            retryable=False,
                            requires_human=True,
                            details={"symbol": symbol, "timeframe": timeframe_name,
                                     "reason": "ea_outdated"},
                        ))
                    if png.exists():
                        return png.read_bytes()
                    # status written just before the PNG is visible; keep polling
                else:
                    reason = status[4:] if status.startswith("err:") else (status or "unknown")
                    code = (
                        "NO_BARS_AT_TIME"
                        if reason.startswith("no bars at")
                        else "SCREENSHOT_FAILED"
                    )
                    raise MT5Error(ErrorDetail(
                        code=code,
                        message=f"EA failed to capture {symbol} {timeframe_name}: {reason}",
                        retryable=(code == "SCREENSHOT_FAILED"
                                   and not reason.startswith(_PERMANENT)),
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
