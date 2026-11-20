"""Compile MQL5 with MetaEditor: run it, read its log, install the result.

Facts from the 2026-11-20 Windows probe (see the design spec): the log is
UTF-16 LE with BOM, MetaEditor's exit code is meaningless (1 on success, 0 on
failure), and `/inc:` must point at the data folder's `MQL5` directory.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

_DIAG = re.compile(
    r"^(?P<path>.+?)(?:\((?P<line>\d+),(?P<col>\d+)\))? : "
    r"(?P<sev>error|warning) (?P<code>\d+): (?P<msg>.*)$"
)
_RESULT = re.compile(r"^Result: (\d+) errors?, (\d+) warnings?")


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    col: int
    severity: Literal["error", "warning"]
    code: int
    message: str


@dataclass(frozen=True)
class CompileLog:
    diagnostics: list[Diagnostic]
    errors: int | None  # None: no "Result:" line, the run did not finish
    warnings: int | None
    raw_text: str


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw:
        return raw.decode("utf-16", errors="replace").lstrip("﻿")
    return raw.decode("utf-8-sig", errors="replace")


def parse_log(raw: bytes) -> CompileLog:
    text = _decode(raw)
    diagnostics: list[Diagnostic] = []
    errors = warnings = None
    for line in text.splitlines():
        line = line.lstrip("﻿")
        if m := _DIAG.match(line):
            diagnostics.append(Diagnostic(
                m["path"], int(m["line"] or 0), int(m["col"] or 0),
                m["sev"], int(m["code"]), m["msg"],  # type: ignore[arg-type]
            ))
        elif m := _RESULT.match(line):
            errors, warnings = int(m[1]), int(m[2])
    return CompileLog(diagnostics, errors, warnings, text)


KIND_FOLDERS: dict[str, str] = {
    "expert": "Experts",
    "indicator": "Indicators",
    "script": "Scripts",
    "service": "Services",
    "library": "Libraries",
}

# One pass so "//" or "/*" inside a string literal is not taken as a comment.
_NOISE = re.compile(
    r'"(?:\\.|[^"\\\n])*"' r"|'(?:\\.|[^'\\\n])*'" r"|//[^\n]*|/\*.*?\*/",
    re.DOTALL,
)
# First match wins; anything else is an Expert Advisor. Entry points must be
# free functions: not `obj.OnStart(` or `CFoo::OnStart(`.
_KIND_RULES = (
    (re.compile(r"#property\s+service\b"), "Services"),
    (re.compile(r"#property\s+library\b"), "Libraries"),
    (re.compile(r"(?<![\w.:])OnCalculate\s*\("), "Indicators"),
    (re.compile(r"(?<![\w.:])OnStart\s*\("), "Scripts"),
)


def read_source(path: Path) -> str:
    """MetaEditor saves UTF-16 or UTF-8, with or without BOM."""
    return _decode(path.read_bytes())


def detect_kind(source_text: str) -> str:
    code = _NOISE.sub(" ", source_text)  # a space keeps `void/*x*/OnStart` two tokens
    for pattern, folder in _KIND_RULES:
        for m in pattern.finditer(code):
            # Only global handlers count, not methods defined inside a class.
            if code.count("{", 0, m.start()) == code.count("}", 0, m.start()):
                return folder
    return "Experts"


def built_ex5(source: Path, mql5: Path, *, since: float) -> Path | None:
    """The newest .ex5 for `source` written at or after `since`, or None.

    Next to the source, except for MQL5/Shared Projects/<rel>, which builds
    to MQL5/<Kind>/Shared Projects/<rel> (seen on Windows, 2026-11-20).
    `since` filters out stale builds from earlier runs; pass 0 to accept any.
    """
    candidates = [source.with_suffix(".ex5")]
    if source.is_relative_to(mql5 / "Shared Projects"):
        rel = source.relative_to(mql5).with_suffix(".ex5")
        candidates += [mql5 / folder / rel for folder in KIND_FOLDERS.values()]
    # 1 s slack for coarse filesystem timestamps.
    fresh = [(c.stat().st_mtime, c) for c in candidates if c.is_file() and c.stat().st_mtime >= since - 1.0]
    return max(fresh)[1] if fresh else None


def install_target(data_dir: Path, kind_folder: str, stem: str) -> Path:
    # Libraries skip Agent/: `#import "X.ex5"` only searches the caller's
    # folder and the Libraries root.
    base = data_dir / "MQL5" / kind_folder
    if kind_folder != "Libraries":
        base = base / "Agent"
    return base / f"{stem}.ex5"


def format_diagnostic(d: Diagnostic, cwd: Path) -> str:
    try:
        path = str(Path(d.path).relative_to(cwd))
    except ValueError:
        path = d.path
    return f"{path}:{d.line}:{d.col}: {d.severity} {d.code}: {d.message}"


class CompileTimeout(Exception):
    """A supervised process (MetaEditor or the tester terminal) timed out."""


def build_command_line(metaeditor: Path, source: Path, inc_dir: Path, log: Path) -> str:
    # A malformed /compile: argument makes MetaEditor compile the whole MQL5
    # tree (seen 2026-11-19), so refuse anything but one real .mq5 file.
    if source.suffix.lower() != ".mq5" or not source.is_file():
        raise ValueError(f"not an .mq5 file: {source}")
    # Built by hand, not via subprocess's list quoting: this exact form is
    # what was verified on Windows, spaces and non-ASCII paths included.
    return f'"{metaeditor}" /compile:"{source}" /inc:"{inc_dir}" /log:"{log}"'


def run_metaeditor(
    cmdline: str,
    *,
    timeout_s: float,
    popen: Callable[..., Any] = subprocess.Popen,
) -> int:
    """Run one compile; the process never outlives this call.

    The probe showed one process per compile and no children, so killing
    the PID is enough. The exit code is returned but means nothing.
    """
    return run_supervised(cmdline, timeout_s=timeout_s, label="MetaEditor", popen=popen)


def run_supervised(
    cmdline: str,
    *,
    timeout_s: float,
    label: str,
    kill: Callable[[Any], None] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
) -> int:
    """Run `cmdline`, return its exit code; it never outlives this call.

    `kill(proc)` replaces `proc.kill()` (the tester terminal needs a tree kill).
    """
    proc = popen(cmdline)
    deadline = time.monotonic() + timeout_s
    try:
        # Short slices: on Windows one long wait blocks Ctrl+C until it returns.
        while True:
            try:
                return proc.wait(timeout=max(0.0, min(0.25, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise CompileTimeout(f"{label} did not finish in {timeout_s:g}s; killed.") from None
    finally:
        if proc.poll() is None:
            (kill or (lambda p: p.kill()))(proc)
            proc.wait()
