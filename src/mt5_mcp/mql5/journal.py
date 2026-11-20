"""The tester agent log lines one backtest wrote, and what they say about the EA.

Agent logs (`Tester\\Agent-*\\logs\\YYYYMMDD.log`, UTF-16) collect every run
of the day, so a run's lines are the bytes added after the sizes recorded
before launch (probe 2026-11-20). Each line is tab-separated:
code, level (0 info, 2 error), time, source, message.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MAX_ERRORS = 50
_MAX_EA_LINES = 200
_BLOCK_ERRORS = 5
_BLOCK_EA_LINES = 10


@dataclass(frozen=True)
class LogLine:
    level: int
    source: str
    message: str


def parse_lines(raw: bytes) -> list[LogLine]:
    text = raw.decode("utf-16-le", errors="replace").lstrip("﻿")
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        try:
            level = int(parts[1])
        except ValueError:
            continue
        out.append(LogLine(level, parts[3], "\t".join(parts[4:])))
    return out


def _logs(tester: Path) -> list[Path]:
    return sorted(tester.glob("Tester/Agent-*/logs/*.log"))


def snapshot_logs(tester: Path) -> dict[Path, int]:
    return {p: p.stat().st_size for p in _logs(tester)}


def read_new(tester: Path, before: dict[Path, int]) -> tuple[list[LogLine], list[str]]:
    lines: list[LogLine] = []
    files: list[str] = []
    for log in _logs(tester):
        start = before.get(log, 0)
        start -= start % 2  # UTF-16: never split a code unit
        with open(log, "rb") as f:  # seek: old days' logs can be large and are unchanged
            f.seek(start)
            raw = f.read()
        if raw:
            lines += parse_lines(raw)
            files.append("\\".join(log.relative_to(tester).parts))
    return lines, files


def _fmt(x: LogLine) -> str:
    return f"{x.source}: {x.message}"


def _crash_error(lines: list[LogLine], ea_stem: str) -> str | None:
    """The line that killed the run: the last error before the first Tester 'critical error'."""
    for i, x in enumerate(lines):
        if x.source == "Tester" and "critical error" in x.message:
            before = [y for y in lines[:i] if y.level != 0]
            own = [y for y in before if y.source.startswith(f"{ea_stem} (")]
            return _fmt((own or before or [x])[-1])
    return None


def summarize(lines: list[LogLine], files: list[str], *, ea_stem: str, optimization: bool) -> dict:
    errors = [_fmt(x) for x in lines if x.level != 0]
    if len(errors) > _MAX_ERRORS:
        # Keep both ends: early non-fatal errors must not push out the fatal one.
        errors = errors[:_MAX_ERRORS // 2] + errors[-(_MAX_ERRORS // 2):]
    if optimization:
        # Several agents and passes; EAs reject input sets on purpose, so nothing here is judged.
        return {"started": None, "crashed": False, "crash_error": None, "errors": errors, "ea_lines": [],
                "lines": len(lines), "log_files": files}
    tester = [x.message for x in lines if x.source == "Tester"]
    # "returns non-zero code" (INIT_FAILED) and "reports incorrect input parameters" share this prefix.
    stopped = any("tester stopped because OnInit" in m for m in tester)
    began = any("testing of " in m and " started" in m for m in tester)
    ea = [x.message for x in lines if x.source.startswith(f"{ea_stem} (")]
    crash = _crash_error(lines, ea_stem)
    return {
        # None: no start line at all (log unreadable or reworded), so it is unknown, not a failure.
        "started": False if stopped else (True if began else None),
        "crashed": crash is not None,
        "crash_error": crash,
        "errors": errors,
        "ea_lines": ea[-_MAX_EA_LINES:],
        "lines": len(lines),
        "log_files": files,
    }


def journal_block(j: dict) -> str | None:
    """Text for the summary; the caller decides when a run needs it."""
    if j["started"] is not False and not j["crashed"] and not j["errors"] and not j["ea_lines"]:
        return None
    out = ["journal:"]
    if j["started"] is not None:
        out.append(f"  started: {'yes' if j['started'] else 'no'}")
    if j["crashed"]:
        out.append("  crashed: yes")
    out += [f"  error: {e}" for e in j["errors"][:_BLOCK_ERRORS]]
    out += [f"  ea: {m}" for m in j["ea_lines"][-_BLOCK_EA_LINES:]]
    return "\n".join(out)
