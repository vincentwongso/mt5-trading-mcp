"""The portable tester install `mt5-mcp backtest` runs in.

A second launch of a running install ignores `/config:` (probed 2026-11-20),
so backtests need their own copy. The copy logs into the same account as the
live terminal, so it must never get charts with EAs on them: only top-level
program files and three login files are copied, never data folders.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from mt5_mcp.config import _user_data_path

CONFIG_FILES = ("accounts.dat", "common.ini", "servers.dat")
# Top-level files were enough on build 6230; the terminal creates the rest.
REQUIRED_DIRS: tuple[str, ...] = ()
# A portable live install keeps charts (with EAs) in Profiles: never copy.
NEVER_COPY = frozenset({"mql5", "profiles", "bases", "tester", "logs", "config"})
_ORIGIN = "origin.json"


class WorkspaceError(Exception):
    pass


class LockHeld(WorkspaceError):
    pass


def default_tester_dir() -> Path:
    return Path(_user_data_path("tester"))


def check_tester_path(tester: Path, install: Path, live_data: Path) -> None:
    """Refuse a tester folder that overlaps the live install or data folder."""
    # realpath: a symlink or junction must not lead back into a live folder.
    t = Path(os.path.realpath(tester))
    for live in (Path(os.path.realpath(install)), Path(os.path.realpath(live_data))):
        if t == live or t.is_relative_to(live) or live.is_relative_to(t):
            raise WorkspaceError(f"tester path {t} overlaps the live MT5 folder {live}; pick a separate folder.")
    ours = (t / _ORIGIN).is_file() or (t / ".backtest.lock").is_file()  # lock file: a setup that failed midway
    if t.is_dir() and any(t.iterdir()) and not ours:
        raise WorkspaceError(f"tester path {t} is not empty and is not a tester install; pick an empty folder.")


def setup_tester(install: Path, live_data: Path, tester: Path) -> None:
    tester.mkdir(parents=True, exist_ok=True)
    # Not ready until write_origin: a refresh that fails midway must not look set up.
    (tester / _ORIGIN).unlink(missing_ok=True)
    for f in install.iterdir():
        if f.is_file():
            shutil.copy2(f, tester / f.name)
    for d in REQUIRED_DIRS:
        if d.casefold() not in NEVER_COPY:
            shutil.copytree(install / d, tester / d, dirs_exist_ok=True)
    config = tester / "Config"
    config.mkdir(exist_ok=True)
    for name in CONFIG_FILES:
        src = live_data / "config" / name
        if not src.is_file():
            raise WorkspaceError(f"{src} not found; log in once in the live terminal, then re-run --setup.")
        shutil.copy2(src, config / name)


def write_origin(tester: Path, install: Path, live_data: Path) -> None:
    (tester / _ORIGIN).write_text(json.dumps({"install": str(install), "data": str(live_data)}), encoding="utf-8")


def read_origin(tester: Path) -> tuple[Path, Path]:
    try:
        d = json.loads((tester / _ORIGIN).read_text(encoding="utf-8"))
        return Path(d["install"]), Path(d["data"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(f"{tester / _ORIGIN} missing or unreadable; re-run mt5-mcp backtest --setup.") from exc


def is_set_up(tester: Path) -> bool:
    return all((tester / p).is_file() for p in ("terminal64.exe", "Config/accounts.dat", _ORIGIN))


_TESTER_BINARIES = ("terminal64.exe", "metatester64.exe")


def build_matches(install: Path, tester: Path) -> bool:
    # copy2 keeps the mtime, so any LiveUpdate on either side shows up here. The agent binary
    # counts too: LiveUpdate can move it while the terminal stays (seen with a pinned terminal).
    for name in _TESTER_BINARIES:
        if not (install / name).exists() and name != "terminal64.exe":
            continue
        try:
            a, b = (install / name).stat(), (tester / name).stat()
        except FileNotFoundError:
            return False
        if (a.st_size, a.st_mtime_ns) != (b.st_size, b.st_mtime_ns):
            return False
    return True


def stage_ea(ex5: Path, tester: Path) -> str:
    if ex5.suffix.lower() != ".ex5" or not ex5.is_file():
        raise WorkspaceError(f"not a compiled .ex5 file: {ex5}")
    target = tester / "MQL5" / "Experts" / "Agent" / ex5.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ex5, target)
    return f"Agent\\{ex5.name}"


def stage_set(src: Path, tester: Path, name: str) -> str:
    raw = src.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    target = tester / "MQL5" / "Profiles" / "Tester" / f"{name}.set"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
    return target.name


def mirror_dependencies(live_mql5: Path, tester_mql5: Path) -> int:
    """Make the tester's compiled programs match the live tree; returns files copied.

    Experts too: `#import "X.ex5"` also searches the EA's own folder. Copies
    whose source is gone are deleted, so a backtest never loads a stale build.
    """
    copied = 0
    for folder in ("Experts", "Indicators", "Libraries"):
        live = {p.relative_to(live_mql5): p for p in (live_mql5 / folder).rglob("*.ex5")}
        for old in (tester_mql5 / folder).rglob("*.ex5"):
            if old.relative_to(tester_mql5) not in live:
                old.unlink()
        for rel, src in live.items():
            dst = tester_mql5 / rel
            s = src.stat()
            # Any difference, not just newer: a restored older build must be copied too.
            if not dst.exists() or (s.st_size, s.st_mtime_ns) != (dst.stat().st_size, dst.stat().st_mtime_ns):
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
    return copied


def new_report_name(stem: str, now: datetime) -> str:
    return f"reports\\{now:%Y%m%dT%H%M%S%f}Z-{stem}"


@contextmanager
def tester_lock(tester: Path, *, wait: bool = False, on_wait: Callable[[], None] | None = None) -> Iterator[None]:
    tester.mkdir(parents=True, exist_ok=True)
    f = open(tester / ".backtest.lock", "a+b")
    try:
        while True:
            try:
                _try_lock(f)
                break
            except OSError:
                if not wait:
                    raise LockHeld("another backtest is running") from None
                if on_wait:
                    on_wait()
                    on_wait = None  # announce once
                time.sleep(1.0)  # poll: msvcrt's blocking mode gives up after 10s
        yield  # the OS drops the lock when the file closes or the process dies
    finally:
        f.close()


def _try_lock(f) -> None:  # noqa: ANN001
    if os.name == "nt":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _newest(folder: Path) -> Path | None:
    logs = list(folder.glob("*.log")) if folder.is_dir() else []
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def terminal_logs(tester: Path) -> list[Path]:
    """The tester terminal's own logs (downloads, connection, tester errors), not the agents'."""
    return sorted(p for d in (tester / "logs", tester / "Tester" / "logs") if d.is_dir() for p in d.glob("*.log"))


def log_tail(tester: Path, n: int = 20, since: dict[Path, int] | None = None) -> str:
    """The newest terminal logs' last lines; with `since`, only lines written after those sizes."""
    parts = []
    for log in (_newest(tester / "logs"), _newest(tester / "Tester" / "logs")):
        if log is None:
            continue
        start = (since or {}).get(log, 0)
        start -= start % 2  # UTF-16: never split a code unit
        with open(log, "rb") as f:
            f.seek(start)
            raw = f.read()
        if not raw:
            continue
        text = raw.decode("utf-16-le", errors="replace") if b"\x00" in raw else raw.decode("utf-8", errors="replace")
        lines = text.lstrip("\ufeff").splitlines()[-n:]
        parts.append("\n".join([f"== {log}", *lines]))
    return "\n".join(parts)


def kill_tree(proc: Any) -> None:
    # taskkill /T also takes the metatester64 agents (probe finding 12).
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    proc.kill()
