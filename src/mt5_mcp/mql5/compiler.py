"""Compile MQL5 with MetaEditor: run it, read its log, install the result.

Facts from the 2026-11-20 Windows probe (see the design spec): the log is
UTF-16 LE with BOM, MetaEditor's exit code is meaningless (1 on success, 0 on
failure), and `/inc:` must point at the data folder's `MQL5` directory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


def format_diagnostic(d: Diagnostic, cwd: Path) -> str:
    try:
        path = str(Path(d.path).relative_to(cwd))
    except ValueError:
        path = d.path
    return f"{path}:{d.line}:{d.col}: {d.severity} {d.code}: {d.message}"
