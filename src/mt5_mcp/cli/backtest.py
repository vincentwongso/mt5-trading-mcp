"""`mt5-mcp backtest` - run the MT5 Strategy Tester on a separate tester install.

Exit codes: 0 finished and report parsed (zero trades included), 2 could not
run (not set up, MT5 updated, lock held, timeout, no fresh report, inputs not
applied). There is no exit 1.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from mt5_mcp.cli.compile import _fail, _program_files, _seconds
from mt5_mcp.config import load_config
from mt5_mcp.mql5.compiler import CompileTimeout, run_supervised
from mt5_mcp.mql5.report import (
    ReportError,
    format_single,
    format_table,
    merge_passes,
    parse_opt_xml,
    parse_single_html,
)
from mt5_mcp.mql5.terminal import LocateError, locate_terminal
from mt5_mcp.mql5.tester import (
    CRITERIA,
    FORWARD,
    MODELS,
    OPTIMIZE,
    PERIODS,
    RunSpec,
    build_ini,
    check_inputs,
    deposit_text,
    ini_value,
    parse_forward,
    parse_set,
    write_ini,
)
from mt5_mcp.mql5.workspace import (
    WorkspaceError,
    build_matches,
    check_tester_path,
    default_tester_dir,
    is_set_up,
    kill_tree,
    log_tail,
    mirror_dependencies,
    new_report_name,
    read_origin,
    setup_tester,
    stage_ea,
    stage_set,
    tester_lock,
    write_origin,
)

_EPILOG = (
    "Run --setup once. The tester install is logged into the same account as "
    "your live terminal. It never trades: no charts or EAs are copied into it, "
    "and live algo trading is switched off for every run."
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        return _main(argv)
    except (WorkspaceError, ReportError, LocateError, ValueError, OSError) as exc:
        return _fail(str(exc))
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {exc}")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mt5-mcp backtest",
        description="Run the MT5 Strategy Tester on a separate tester install.",
        epilog=_EPILOG,
    )
    p.add_argument("ea", nargs="?", help="The .ex5 to test (the path `mt5-mcp compile` prints).")
    p.add_argument("--setup", action="store_true", help="Create or refresh the tester install, then exit.")
    p.add_argument("--symbol", type=ini_value)
    p.add_argument("--period", choices=PERIODS)
    p.add_argument("--from", dest="date_from", type=_date, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", type=_date, help="YYYY-MM-DD")
    p.add_argument("--set", help="MT5 .set file: Name=value, or Name=value||start||step||stop||Y to optimise.")
    p.add_argument("--deposit", type=float, default=10000.0)
    p.add_argument("--currency", type=ini_value, default="USD")
    p.add_argument("--leverage", type=int, default=100)
    p.add_argument("--model", choices=list(MODELS), default="ohlc", help="ohlc = 1-minute OHLC (default), ticks, real = real ticks.")
    p.add_argument("--optimize", choices=list(OPTIMIZE))
    p.add_argument("--criterion", choices=list(CRITERIA), default="balance")
    p.add_argument("--forward", type=parse_forward, default="1/3",
                   help="Held-out forward period for --optimize: 1/2, 1/3 (default), 1/4, YYYY-MM-DD or off.")
    p.add_argument("--top", type=int, default=20, help="Optimisation rows to print (default 20).")
    p.add_argument("--timeout", type=_seconds, default=600.0, help="Seconds before the terminal is killed (default 600).")
    p.add_argument("--tester-path", default=None, help="Tester install folder (default: per-user data dir).")
    p.add_argument("--terminal-path", default=None, help="Live terminal64.exe or its folder. Overrides [mt5] terminal_path.")
    p.add_argument("--data-path", default=None, help="Live terminal data folder. Overrides [mt5] data_path.")
    p.add_argument("--config", default=None, help="Path to config TOML (default: per-OS user config dir).")
    return p


def _locate(args: argparse.Namespace, cfg):  # noqa: ANN001
    return locate_terminal(
        terminal_path=args.terminal_path or cfg.mt5.terminal_path,
        data_path=args.data_path or cfg.mt5.data_path,
        program_files=_program_files(),
        appdata=Path(os.environ["APPDATA"]) if os.environ.get("APPDATA") else None,
    )


def _same_dir(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _main(argv: list[str]) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    tester = Path(os.path.abspath(args.tester_path)) if args.tester_path else default_tester_dir()
    cfg = load_config(Path(args.config) if args.config else None)

    if args.setup:
        paths = _locate(args, cfg)
        check_tester_path(tester, paths.install_dir, paths.data_dir)
        with tester_lock(tester):
            setup_tester(paths.install_dir, paths.data_dir, tester)
            write_origin(tester, paths.install_dir, paths.data_dir)
        print(f"tester: {tester}")
        if not cfg.mt5.terminal_path:
            # Probed: MetaTrader5.initialize() with no path attaches to a running tester terminal.
            print("warning: set [mt5] terminal_path, or the MCP server may attach to the tester "
                  "terminal while a backtest runs.", file=sys.stderr)
        return 0

    missing = [f"--{n}" for n in ("symbol", "period", "from", "to")
               if getattr(args, {"from": "date_from", "to": "date_to"}.get(n, n)) is None]
    if not args.ea or missing:
        parser.error(f"need an .ex5 and {', '.join(missing) or 'nothing else'} (or --setup)")
    if args.date_from >= args.date_to:
        parser.error("--from must be before --to")
    if args.optimize and args.forward not in FORWARD and not args.date_from < date.fromisoformat(args.forward) < args.date_to:
        parser.error("--forward date must fall strictly between --from and --to")

    set_file = parse_set(Path(args.set).read_bytes()) if args.set else None
    if args.optimize and not (set_file and set_file.optimized):
        return _fail("nothing to optimise: mark inputs with ||Y in the .set (--set)")

    if not is_set_up(tester):
        return _fail(f"no tester install at {tester}: run mt5-mcp backtest --setup first")

    ea = Path(os.path.abspath(args.ea))
    with tester_lock(tester):  # held from the origin check on, so a --setup cannot swap it mid-run
        install, data = read_origin(tester)  # no re-discovery: same tree setup copied from
        if args.terminal_path or args.data_path:
            # The tester keeps setup's logins, so other paths would mix two terminals.
            paths = _locate(args, cfg)
            if not (_same_dir(paths.install_dir, install) and _same_dir(paths.data_dir, data)):
                return _fail("--terminal-path/--data-path differ from the tester's setup; "
                             "re-run mt5-mcp backtest --setup with them")
        if not build_matches(install, tester):
            return _fail("MT5 was updated; re-run mt5-mcp backtest --setup")
        report = new_report_name(ea.stem, datetime.now(timezone.utc))
        (tester / "reports").mkdir(exist_ok=True)
        mirror_dependencies(data / "MQL5", tester / "MQL5")  # before staging: it deletes unknown .ex5s
        live_experts = data / "MQL5" / "Experts"
        if ea.suffix.lower() == ".ex5" and ea.is_file() and ea.is_relative_to(live_experts):
            expert = "\\".join(ea.relative_to(live_experts).parts)  # mirrored with its folder's siblings
        else:
            expert = stage_ea(ea, tester)
        set_name = stage_set(Path(args.set), tester, report.rsplit("\\", 1)[-1]) if args.set else None
        spec = RunSpec(
            expert=expert, symbol=args.symbol, period=args.period,
            date_from=args.date_from, date_to=args.date_to, deposit=args.deposit,
            currency=args.currency, leverage=args.leverage, model=args.model,
            optimize=args.optimize, criterion=args.criterion, forward=args.forward,
            set_name=set_name, report=report,
        )
        base = tester / report.replace("\\", "/")
        # Success is this run's uniquely named report, never the exit code.
        out = base.with_name(base.name + (".xml" if args.optimize else ".htm"))
        with tempfile.TemporaryDirectory(prefix="mt5-backtest-") as tmp:
            ini = Path(tmp) / "backtest.ini"
            write_ini(ini, build_ini(spec))
            cmdline = f'"{tester / "terminal64.exe"}" /portable /config:"{ini}"'
            for attempt in (1, 2):
                try:
                    code = run_supervised(cmdline, timeout_s=args.timeout, label="terminal", kill=kill_tree)
                except CompileTimeout as exc:
                    return _fail(f"{exc}\n{log_tail(tester)}")
                if out.is_file() or code != 0 or attempt == 2:
                    break
                # Seen on Windows: the first run that downloads M1 history finishes the test
                # and exits 0 without writing the report; the same run again writes it.
                print("note: the terminal exited without writing a report; running it once more", file=sys.stderr)

    if not out.is_file():
        return _fail(f"no report written ({out}); the run failed:\n{log_tail(tester)}")

    # Results are only comparable under the same settings, so every summary leads with them.
    settings = (f"settings: {args.symbol} {args.period} {args.date_from}..{args.date_to} model={args.model} "
                f"deposit={deposit_text(args.deposit)} {args.currency} leverage=1:{args.leverage}")
    if args.optimize:
        settings += f" optimize={args.optimize} criterion={args.criterion} forward={args.forward}"

    if not args.optimize:
        result = parse_single_html(out.read_bytes())
        problem = check_inputs(set_file, result.inputs, optimized_names=None) if set_file else None
        if problem:
            return _fail(problem)
        print(settings)
        print(format_single(result, out))
        return 0

    back = parse_opt_xml(out.read_bytes())
    forward = None
    if args.forward != "off":
        fwd = base.with_name(base.name + ".forward.xml")
        if not fwd.is_file():
            return _fail(f"no forward report written ({fwd}):\n{log_tail(tester)}")
        forward = parse_opt_xml(fwd.read_bytes())
    problem = check_inputs(set_file, {}, optimized_names=back.inputs) if set_file else None
    if problem:
        return _fail(problem)
    if set_file and set_file.fixed:
        # The optimisation report lists only optimised inputs.
        print(f"note: fixed inputs not checked in optimisation runs: {', '.join(set_file.fixed)}", file=sys.stderr)
    print(settings)
    print(format_table(merge_passes(back, forward), args.top, out))
    return 0
