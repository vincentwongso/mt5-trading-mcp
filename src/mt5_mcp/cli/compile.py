"""`mt5-mcp compile <file.mq5>` - compile MQL5 with the local MetaEditor.

Exit codes: 0 compiled (warnings allowed) and installed, 1 compile errors,
2 could not run (setup, timeout, unreadable log, install failed).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from mt5_mcp.config import load_config
from mt5_mcp.mql5.compiler import (
    KIND_FOLDERS,
    CompileTimeout,
    build_command_line,
    built_ex5,
    detect_kind,
    format_diagnostic,
    install_target,
    parse_log,
    read_source,
    run_metaeditor,
)
from mt5_mcp.mql5.terminal import LocateError, locate_terminal

_EPILOG = (
    "Clean builds install to <data>/MQL5/<Kind>/Agent/<name>.ex5 (libraries: "
    "MQL5/Libraries/). Reinstalling an EA that is attached to a live chart "
    "reloads the new code on that chart."
)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _program_files() -> list[Path]:
    keys = ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
    return [Path(p) for p in dict.fromkeys(os.environ.get(k, "") for k in keys) if p]


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    # Windows pipes use the ANSI code page; a user name outside it must not
    # turn a finished build into a traceback.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        return _main(argv)
    except Exception as exc:  # exit 1 means compile errors; anything else is 2
        return _fail(f"{type(exc).__name__}: {exc}")


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="mt5-mcp compile",
        description="Compile one MQL5 source file with the local MetaEditor.",
        epilog=_EPILOG,
    )
    parser.add_argument("source", help="Path to the .mq5 file.")
    parser.add_argument("--kind", choices=list(KIND_FOLDERS), help="Override program type detection.")
    parser.add_argument("--no-install", action="store_true", help="Leave the .ex5 next to the source only.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Seconds before MetaEditor is killed (default 60).")
    parser.add_argument("--terminal-path", default=None, help="terminal64.exe or its folder. Overrides [mt5] terminal_path.")
    parser.add_argument("--data-path", default=None, help="Terminal data folder (holds MQL5/). Overrides [mt5] data_path.")
    parser.add_argument("--config", default=None, help="Path to config TOML (default: per-OS user config dir).")
    args = parser.parse_args(argv)

    source = Path(args.source).absolute()
    try:
        cfg = load_config(Path(args.config) if args.config else None)
        paths = locate_terminal(
            terminal_path=args.terminal_path or cfg.mt5.terminal_path,
            data_path=args.data_path or cfg.mt5.data_path,
            program_files=_program_files(),
            appdata=Path(os.environ["APPDATA"]) if os.environ.get("APPDATA") else None,
        )
    except (LocateError, ValueError, OSError) as exc:
        return _fail(str(exc))
    print(f"data folder: {paths.data_dir}", file=sys.stderr)

    mql5 = paths.data_dir / "MQL5"
    tmp = Path(tempfile.mkdtemp(prefix="mt5-compile-"))
    try:
        log_path = tmp / "compile.log"
        try:
            cmdline = build_command_line(paths.metaeditor, source, mql5, log_path)
            run_metaeditor(cmdline, timeout_s=args.timeout)
        except (ValueError, CompileTimeout, OSError) as exc:
            return _fail(str(exc))
        raw = log_path.read_bytes() if log_path.exists() else b""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    log = parse_log(raw)
    if log.errors is None:
        tail = "\n".join(log.raw_text.splitlines()[-20:])
        return _fail(f"MetaEditor log has no Result line:\n{tail}")
    cwd = Path.cwd()
    for d in log.diagnostics:
        print(format_diagnostic(d, cwd))
    print(f"Result: {_plural(log.errors, 'error')}, {_plural(log.warnings or 0, 'warning')}")
    if log.errors:
        return 1
    if args.no_install:
        return 0

    ex5 = built_ex5(source, mql5)
    if ex5 is None:
        return _fail(f"clean build but no .ex5 found for {source}")
    # Already inside a kind folder (source lives there, or a Shared Project).
    if any(ex5.is_relative_to(mql5 / folder) for folder in KIND_FOLDERS.values()):
        print(f"installed: {ex5}")
        return 0
    kind = KIND_FOLDERS[args.kind] if args.kind else detect_kind(read_source(source))
    target = install_target(paths.data_dir, kind, source.stem)
    if target.exists():
        print(f"replacing existing: {target}", file=sys.stderr)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ex5, target)
    except OSError as exc:
        return _fail(f"install failed: {exc}")
    print(f"installed: {target}")
    return 0
