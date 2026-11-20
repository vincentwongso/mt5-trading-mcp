"""`mt5-mcp backtest` - run the MT5 Strategy Tester on a separate tester install.

Exit codes: 0 finished and report parsed (zero trades included), 2 could not
run (not set up, MT5 updated, lock held, timeout, no fresh report, inputs not
applied) or, for a single run, the EA failed to start or crashed. There is no
exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from mt5_mcp.cli.compile import _fail, _program_files, _seconds
from mt5_mcp.config import load_config
from mt5_mcp.mql5.compiler import CompileTimeout, run_supervised
from mt5_mcp.mql5.hostpath import host_paths
from mt5_mcp.mql5.journal import journal_block, read_new, snapshot_logs, summarize
from mt5_mcp.mql5.report import (
    ReportError,
    format_single,
    format_table,
    merge_passes,
    parse_opt_xml,
    parse_single_html,
)
from mt5_mcp.mql5.results import optimization_document, single_document, write_document
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
    p.add_argument("--wait", action="store_true",
                   help="If another backtest holds the tester, wait for it instead of exiting 2.")
    p.add_argument("--out", default=None,
                   help="Copy the report and write the JSON into this folder; printed paths name the copies.")
    p.add_argument("--json", action="store_true",
                   help="Print the run's JSON (settings, metrics, deals, balance, drawdowns, journal) instead of the summary.")
    p.add_argument("--read", metavar="REPORT", default=None,
                   help="Print the JSON for an existing .htm or .xml report, without running anything.")
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


def _dump(doc: dict) -> None:
    print(json.dumps(doc, indent=1))


def _read_report(path: Path) -> int:
    """Rebuild the JSON from an old report. Prints only: a run's journal can't be recaptured."""
    raw = path.read_bytes()
    if path.suffix.lower() == ".xml":
        fwd = path.with_name(path.stem + ".forward.xml")
        rows = merge_passes(parse_opt_xml(raw), parse_opt_xml(fwd.read_bytes()) if fwd.is_file() else None)
        keys = ("symbol", "period", "from", "to", "model", "deposit", "currency", "leverage",
                "optimize", "criterion", "forward")
        _dump(optimization_document(dict.fromkeys(keys), rows, None, path))
        return 0
    r = parse_single_html(raw)
    h = r.header
    lev = h.get("leverage") or ""
    settings = {
        "symbol": h.get("symbol"), "period": h.get("period"), "from": h.get("from"), "to": h.get("to"),
        "model": None, "deposit": float(h["deposit"]) if h.get("deposit") else None,
        "currency": h.get("currency"), "leverage": int(lev.split(":")[1]) if lev.startswith("1:") else None,
    }
    _dump(single_document(settings, r, None, path))
    return 0


def _unreadable(exc: ReportError, journal: dict | None, tester: Path) -> int:
    """A report MT5 filled with 'n/a' (e.g. no tick history): the reason is in the tester log."""
    errors = (journal or {}).get("errors") or []
    return _fail("\n".join([str(exc), *(f"  error: {e}" for e in errors[:5])]) if errors
                 else f"{exc}\n{log_tail(tester)}")


def _announce_wait() -> None:
    print("waiting for another backtest to finish...", file=sys.stderr)


def _deliver(out_dir: Path | None, reports: list[Path]) -> list[Path]:
    """Copy the reports into --out; the copies are what the caller is told about."""
    if out_dir is None:
        return reports
    out_dir.mkdir(parents=True, exist_ok=True)
    return [Path(shutil.copy2(r, out_dir / r.name)) for r in reports]


def _with_lines(text: str, *extra: str | None) -> str:
    """Insert lines just before the final `report:` line."""
    lines = text.splitlines()
    return "\n".join([*lines[:-1], *(e for e in extra if e), lines[-1]])


def _main(argv: list[str]) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.out and (args.read or args.setup):
        parser.error("--out goes with a run, not --setup or --read")
    out_dir = Path(os.path.abspath(args.out)) if args.out else None
    if args.read:
        if args.ea or args.setup:
            parser.error("--read takes a report only, not an .ex5 or --setup")
        return _read_report(Path(args.read))
    tester = Path(os.path.abspath(args.tester_path)) if args.tester_path else default_tester_dir()
    cfg = load_config(Path(args.config) if args.config else None)

    if args.setup:
        paths = _locate(args, cfg)
        check_tester_path(tester, paths.install_dir, paths.data_dir)
        with tester_lock(tester, wait=args.wait, on_wait=_announce_wait):
            setup_tester(paths.install_dir, paths.data_dir, tester)
            write_origin(tester, paths.install_dir, paths.data_dir)
        print(host_paths(f"tester: {tester}"))
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

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)  # an unusable --out must fail before a long run, not after

    ea = Path(os.path.abspath(args.ea))
    with tester_lock(tester, wait=args.wait, on_wait=_announce_wait):  # held from the origin check on, so a --setup cannot swap it mid-run
        if not is_set_up(tester):  # under the lock: a refresh removes origin.json while it copies
            return _fail(f"no tester install at {tester}: run mt5-mcp backtest --setup first")
        install, data = read_origin(tester)  # no re-discovery: same tree setup copied from
        if args.terminal_path or args.data_path:
            # The tester keeps setup's logins, so other paths would mix two terminals.
            paths = _locate(args, cfg)
            if not (_same_dir(paths.install_dir, install) and _same_dir(paths.data_dir, data)):
                return _fail("--terminal-path/--data-path differ from the tester's setup; "
                             "re-run mt5-mcp backtest --setup with them")
        if not build_matches(install, tester):
            # LiveUpdate replaced the terminal; an unattended agent cannot be asked to re-run --setup.
            try:
                setup_tester(install, data, tester)
                write_origin(tester, install, data)
                if not build_matches(install, tester):
                    raise WorkspaceError("the tester copy still differs from the live terminal")
            except (OSError, WorkspaceError) as exc:
                return _fail(f"MT5 was updated and refreshing the tester failed: {exc}; "
                             "re-run mt5-mcp backtest --setup")
            print("MT5 was updated; refreshed the tester install", file=sys.stderr)
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
        if args.optimize:
            # An identical re-run is served from this cache and writes no forward report.
            for cached in (tester / "Tester" / "cache").glob("*.opt"):
                cached.unlink(missing_ok=True)
        before = snapshot_logs(tester)  # once, so a retried run's lines are kept too
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
        # Under the lock: the agent logs are shared, so a later run's lines must not land in this journal.
        try:
            lines, files = read_new(tester, before)
            journal = summarize(lines, files, ea_stem=ea.stem, optimization=bool(args.optimize))
        except OSError as exc:  # the report is the result; a missing journal must not lose it
            print(f"note: could not read the tester log ({exc}); the JSON has no journal", file=sys.stderr)
            journal = None

    if not out.is_file():
        return _fail(f"no report written ({out}); the run failed:\n{log_tail(tester)}")

    json_path = (out_dir or base.parent) / (base.name + ".json")

    # Results are only comparable under the same settings, so every summary leads with them.
    settings = {"symbol": args.symbol, "period": args.period, "from": str(args.date_from), "to": str(args.date_to),
                "model": args.model, "deposit": float(deposit_text(args.deposit)), "currency": args.currency, "leverage": args.leverage}
    line = (f"settings: {args.symbol} {args.period} {args.date_from}..{args.date_to} model={args.model} "
            f"deposit={deposit_text(args.deposit)} {args.currency} leverage=1:{args.leverage}")
    if args.optimize:
        settings.update(optimize=args.optimize, criterion=args.criterion, forward=args.forward)
        line += f" optimize={args.optimize} criterion={args.criterion} forward={args.forward}"

    if not args.optimize:
        try:
            result = parse_single_html(out.read_bytes())
        except ReportError as exc:
            return _unreadable(exc, journal, tester)
        out = _deliver(out_dir, [out])[0]
        doc = single_document(settings, result, journal, out)
        write_document(doc, json_path)
        if args.json:
            _dump(doc)  # also on exit 2 below, so the agent gets the journal either way
        problem = check_inputs(set_file, result.inputs, optimized_names=None) if set_file else None
        j = journal or {"started": None, "crashed": False, "crash_error": None, "errors": [], "ea_lines": []}
        block = journal_block(j)
        if not problem and j["started"] is False:
            first = j["errors"][0] if j["errors"] else "the test never started"
            problem = f"EA failed to start: {first}"
        elif not problem and j["crashed"]:
            problem = f"EA hit a runtime error: {j['crash_error']}"
        if problem:
            paths = None if args.json else f"json: {json_path}\nreport: {out}"  # the full results stay readable
            return _fail("\n".join(x for x in (problem, block if j["started"] is False or j["crashed"] else None,
                                               paths) if x))
        if journal is not None and j["started"] is None:
            print("note: the tester log has no 'testing of ... started' line, so whether the EA started "
                  "is unknown; check trades and the journal", file=sys.stderr)
        if not args.json:
            show = block if result.metrics["trades"] == 0 or j["errors"] else None
            print(line)
            print(host_paths(_with_lines(format_single(result, out), show, f"json: {json_path}")))
        return 0

    try:
        back = parse_opt_xml(out.read_bytes())
    except ReportError as exc:
        return _unreadable(exc, journal, tester)
    forward = None
    if args.forward != "off":
        fwd = base.with_name(base.name + ".forward.xml")
        if not fwd.is_file():
            return _fail(f"no forward report written ({fwd}):\n{log_tail(tester)}")
        forward = parse_opt_xml(fwd.read_bytes())
    rows = merge_passes(back, forward)
    out = _deliver(out_dir, [out, fwd] if forward is not None else [out])[0]
    doc = optimization_document(settings, rows, journal, out)
    write_document(doc, json_path)
    if args.json:
        _dump(doc)
    problem = check_inputs(set_file, {}, optimized_names=back.inputs) if set_file else None
    if problem:
        return _fail(problem)
    if set_file and set_file.fixed:
        # The optimisation report lists only optimised inputs.
        print(f"note: fixed inputs not checked in optimisation runs: {', '.join(set_file.fixed)}", file=sys.stderr)
    if not args.json:
        print(line)
        print(host_paths(_with_lines(format_table(rows, args.top, out), f"json: {json_path}")))
    return 0
