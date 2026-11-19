"""Find the MT5 install, its MetaEditor and its data folder, offline.

No terminal connection: portable is a launch flag, not something on disk, so
the data folder is picked from the candidates by whose `logs/` was written
last (the terminal in use writes its daily log there). Reused by the phase 2
backtest command.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_FIX = "Set [mt5] terminal_path / data_path in the config, or pass --terminal-path / --data-path."


@dataclass(frozen=True)
class TerminalPaths:
    install_dir: Path
    metaeditor: Path
    data_dir: Path


class LocateError(Exception):
    pass


def _norm(p: str) -> str:
    return p.strip().rstrip("\\/").casefold()


def _newest_log(d: Path) -> float:
    logs = d / "logs"
    times = [f.stat().st_mtime for f in logs.iterdir() if f.is_file()] if logs.is_dir() else []
    return max(times, default=-1.0)


def _find_install(terminal_path: str, program_files: list[Path]) -> Path:
    if terminal_path:
        p = Path(terminal_path).absolute()
        return p.parent if p.suffix.lower() == ".exe" else p
    found = sorted({m.parent for pf in program_files if pf.is_dir() for m in pf.glob("*/metaeditor64.exe")})
    if len(found) == 1:
        return found[0]
    if not found:
        raise LocateError(f"No MetaTrader 5 install with metaeditor64.exe found. {_FIX}")
    listing = "\n  ".join(str(f) for f in found)
    raise LocateError(f"Several MetaTrader 5 installs found:\n  {listing}\n{_FIX}")


def _find_data(install: Path, appdata: Path | None) -> Path:
    candidates = [install] if (install / "MQL5").is_dir() else []
    terminals = appdata / "MetaQuotes" / "Terminal" if appdata else None
    if terminals and terminals.is_dir():
        for d in sorted(terminals.iterdir()):
            origin = d / "origin.txt"
            if origin.is_file() and (d / "MQL5").is_dir():
                text = origin.read_bytes().decode("utf-16", errors="replace").lstrip("﻿")
                if _norm(text) == _norm(str(install)):
                    candidates.append(d)
    if not candidates:
        raise LocateError(f"No MQL5 data folder found for {install}. {_FIX}")
    if len(candidates) == 1:
        return candidates[0]
    ranked = sorted(candidates, key=_newest_log, reverse=True)
    if _newest_log(ranked[0]) < 0:
        listing = "\n  ".join(str(c) for c in candidates)
        raise LocateError(f"Several data folders for {install}, none with logs:\n  {listing}\n{_FIX}")
    return ranked[0]


def locate_terminal(
    *,
    terminal_path: str = "",
    data_path: str = "",
    program_files: list[Path],
    appdata: Path | None,
) -> TerminalPaths:
    install = _find_install(terminal_path, program_files)
    metaeditor = install / "metaeditor64.exe"
    if not metaeditor.is_file():
        raise LocateError(f"metaeditor64.exe not found in {install}. {_FIX}")
    if data_path:
        data = Path(data_path).absolute()
        if not (data / "MQL5").is_dir():
            raise LocateError(f"{data} has no MQL5 folder. {_FIX}")
    else:
        data = _find_data(install, appdata)
    return TerminalPaths(install, metaeditor, data)
