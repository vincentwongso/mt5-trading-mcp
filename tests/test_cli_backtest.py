"""`mt5-mcp backtest` end to end, with the terminal and discovery faked."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import pytest

import mt5_mcp.cli.backtest as cli
from mt5_mcp.mql5 import workspace as ws
from mt5_mcp.mql5.compiler import CompileTimeout
from mt5_mcp.mql5.terminal import TerminalPaths

FIX = Path(__file__).parent / "fixtures" / "mql5" / "reports"
JOURNAL = Path(__file__).parent / "fixtures" / "mql5" / "journal"


def _ini(cmdline: str) -> dict[str, str]:
    path = Path(re.search(r'/config:"([^"]+)"', cmdline)[1])
    lines = path.read_bytes().decode("utf-16").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


@pytest.fixture
def env(tmp_path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    (install / "terminal64.exe").write_bytes(b"exe")
    (install / "metaeditor64.exe").write_bytes(b"me")
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    for f in ws.CONFIG_FILES:
        (data / "config" / f).write_bytes(b"x")
    (data / "MQL5" / "Indicators" / "Agent").mkdir(parents=True)
    (data / "MQL5" / "Indicators" / "Agent" / "ind.ex5").write_bytes(b"ind")
    tester = tmp_path / "tester"
    cfg = tmp_path / "config.toml"
    cfg.write_text("[mt5]\nterminal_path = 'C:/x/terminal64.exe'\n")
    ea = tmp_path / "MyEA.ex5"
    ea.write_bytes(b"EX5")
    paths = TerminalPaths(install, install / "metaeditor64.exe", data)
    monkeypatch.setattr(cli, "locate_terminal", lambda **kw: paths)
    state = {"single": "single_en.htm", "opt": "opt_full_fwd.xml", "fwd": "opt_full_fwd.forward.xml",
             "write": True, "calls": [], "inis": [], "journal": "normal.log"}

    def fake_run(cmdline, *, timeout_s, label, kill=None):
        state["calls"].append(cmdline)
        ini = _ini(cmdline)
        state["inis"].append(ini)
        if state["write"] == "timeout":
            raise CompileTimeout(f"{label} did not finish in {timeout_s:g}s; killed.")
        if state["write"]:
            log = tester / "Tester" / "Agent-127.0.0.1-3000" / "logs" / "20261120.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "ab") as f:  # the agent log collects every run of the day
                f.write((JOURNAL / state["journal"]).read_bytes())
            out = tester / ini["Report"].replace("\\", "/")
            if ini["Optimization"] == "0":
                shutil.copy(FIX / state["single"], out.with_name(out.name + ".htm"))
            else:
                shutil.copy(FIX / state["opt"], out.with_name(out.name + ".xml"))
                if ini["ForwardMode"] != "0":
                    shutil.copy(FIX / state["fwd"], out.with_name(out.name + ".forward.xml"))
        return 0

    monkeypatch.setattr(cli, "run_supervised", fake_run)
    state.update(tester=tester, cfg=cfg, ea=ea, data=data, install=install, tmp=tmp_path)
    return state


def setup(env, *extra):
    return cli.main(["--setup", "--tester-path", str(env["tester"]), "--config", str(env["cfg"]), *extra])


def bt(env, *extra, setup_first=True):
    if setup_first and not (env["tester"] / "origin.json").exists():
        assert setup(env) == 0
    base = [str(env["ea"]), "--symbol", "EURUSD", "--period", "H1", "--from", "2026-10-01",
            "--to", "2026-11-01", "--tester-path", str(env["tester"]), "--config", str(env["cfg"])]
    return cli.main([*base, *extra])


def write_set(env, text, name="in.set"):
    p = env["tmp"] / name
    p.write_text(text)
    return str(p)


def test_single_run_prints_summary_exit0(env, capsys):
    assert bt(env) == 0
    out = capsys.readouterr().out
    assert "net_profit: 109.31" in out and "trades: 23" in out
    assert re.search(r"report: .*Z-MyEA\.htm", out)
    ini = env["inis"][-1]
    assert ini["Expert"] == "Agent\\MyEA.ex5" and ini["Model"] == "1" and ini["AllowLiveTrading"] == "0"
    assert (env["tester"] / "MQL5" / "Indicators" / "Agent" / "ind.ex5").is_file()


def test_optimize_prints_table_ranked_by_forward_exit0(env, capsys):
    s = write_set(env, "MaximumRisk=0.02\nDecreaseFactor=3\nMovingPeriod=12||6||2||30||Y\nMovingShift=6||0||2||10||Y\n")
    setup(env)
    capsys.readouterr()
    assert bt(env, "--optimize", "full", "--set", s, "--top", "3") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ("settings: EURUSD H1 2026-10-01..2026-11-01 model=ohlc deposit=10000 USD "
                        "leverage=1:100 optimize=full criterion=balance forward=1/3")
    assert lines[1].split()[:3] == ["rank", "pass", "fwd_result"]
    assert lines[2].split()[:2] == ["1", "68"]
    assert len(lines) == 1 + 1 + 3 + 1 + 1  # settings, header, 3 rows, json, report


def test_ini_has_forward_third_by_default_with_optimize(env):
    s = write_set(env, "MovingPeriod=12||6||2||30||Y\nMovingShift=6||0||2||10||Y\n")
    bt(env, "--optimize", "genetic", "--set", s)
    ini = env["inis"][-1]
    assert ini["Optimization"] == "2" and ini["ForwardMode"] == "2"
    assert ini["ExpertParameters"].endswith(".set")


def test_forward_off_uses_back_only(env, capsys):
    env["opt"] = "opt_full.xml"
    s = write_set(env, "MovingPeriod=12||6||2||30||Y\nMovingShift=6||0||2||10||Y\n")
    assert bt(env, "--optimize", "full", "--set", s, "--forward", "off") == 0
    assert env["inis"][-1]["ForwardMode"] == "0"
    assert "fwd_result" not in capsys.readouterr().out


def test_no_report_exit2_with_log_tail(env, monkeypatch, capsys):
    assert bt(env) == 0  # leaves an older report behind
    env["write"] = False
    original = cli.run_supervised

    def run(cmdline, **kw):
        (env["tester"] / "logs").mkdir(exist_ok=True)
        (env["tester"] / "logs" / "20261120.log").write_bytes("tester EX5 not found".encode("utf-16"))
        return original(cmdline, **kw)

    monkeypatch.setattr(cli, "run_supervised", run)
    capsys.readouterr()
    assert bt(env) == 2
    err = capsys.readouterr().err
    assert "no report" in err and "== " in err and "EX5 not found" in err


def test_not_set_up_exit2(env, capsys):
    assert bt(env, setup_first=False) == 2
    assert "--setup" in capsys.readouterr().err


def _touch_live(env):
    exe = env["install"] / "terminal64.exe"
    st = exe.stat()
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))


def test_build_mismatch_refreshes_and_runs(env, capsys):
    setup(env)
    _touch_live(env)
    assert bt(env) == 0
    assert "MT5 was updated; refreshed the tester install" in capsys.readouterr().err
    assert ws.build_matches(env["install"], env["tester"])


def test_refresh_failure_exit2_with_hint(env, monkeypatch, capsys):
    setup(env)
    _touch_live(env)

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "setup_tester", boom)
    assert bt(env) == 2
    err = capsys.readouterr().err
    assert "disk full" in err and "re-run mt5-mcp backtest --setup" in err


def test_refresh_happens_after_waiting_for_the_lock(env, capsys):
    setup(env)
    _touch_live(env)
    t = _held(env["tester"], 1.0)
    assert bt(env, "--wait") == 0
    t.join()
    assert "refreshed the tester install" in capsys.readouterr().err


def test_lock_held_exit2(env, capsys):
    setup(env)
    with ws.tester_lock(env["tester"]):
        assert bt(env) == 2
    assert "another backtest is running" in capsys.readouterr().err


def test_set_input_mismatch_exit2_names_input(env, capsys):
    s = write_set(env, "MaximumRisk=0.02\nBogusInput=7\n")
    assert bt(env, "--set", s) == 2
    assert "BogusInput" in capsys.readouterr().err


def test_timeout_exit2_and_lock_released(env, capsys):
    setup(env)
    env["write"] = "timeout"
    assert bt(env, "--timeout", "5") == 2
    assert "did not finish" in capsys.readouterr().err
    with ws.tester_lock(env["tester"]):
        pass


def test_optimize_without_y_inputs_exit2(env, capsys):
    s = write_set(env, "MovingPeriod=12\n")
    assert bt(env, "--optimize", "full", "--set", s) == 2
    assert "nothing to optimise" in capsys.readouterr().err
    assert bt(env, "--optimize", "full") == 2


@pytest.mark.parametrize("extra", [
    ["--from", "2026-11-02"],
    ["--optimize", "full", "--forward", "2026-12-01"],
    ["--period", "H7"],
    ["--timeout", "nan"],
])
def test_bad_arguments_exit2(env, extra, capsys):
    setup(env)
    s = write_set(env, "MovingPeriod=12||6||2||30||Y\n")
    if "--optimize" in extra:
        extra = [*extra, "--set", s]
    with pytest.raises(SystemExit) as e:
        bt(env, *extra)
    assert e.value.code == 2


def test_setup_creates_tester_and_never_touches_live_data(env, capsys):
    def snapshot():
        return sorted((str(p), p.stat().st_mtime_ns) for p in env["data"].rglob("*"))
    before = snapshot()
    assert setup(env) == 0
    assert bt(env) == 0
    assert snapshot() == before
    assert f"tester: {env['tester']}" in capsys.readouterr().out
    assert ws.read_origin(env["tester"]) == (env["install"], env["data"])


def test_setup_warns_when_terminal_path_unset(env, capsys):
    env["cfg"].write_text("[mt5]\nterminal_path = ''\n")
    assert setup(env) == 0
    assert "terminal_path" in capsys.readouterr().err


def test_run_uses_recorded_origin_not_rediscovery(env, monkeypatch):
    setup(env)

    def ambiguous(**kw):
        raise AssertionError("runs must not re-discover the live install")

    monkeypatch.setattr(cli, "locate_terminal", ambiguous)
    assert bt(env) == 0


def test_optimize_notes_unverified_fixed_inputs(env, capsys):
    s = write_set(env, "MaximumRisk=0.02\nMovingPeriod=12||6||2||30||Y\nMovingShift=6||0||2||10||Y\n")
    assert bt(env, "--optimize", "full", "--set", s) == 0
    err = capsys.readouterr().err
    assert "not checked" in err and "MaximumRisk" in err


def test_setup_refuses_tester_path_in_live_data(env, capsys):
    assert cli.main(["--setup", "--tester-path", str(env["data"]), "--config", str(env["cfg"])]) == 2
    assert not (env["data"] / "terminal64.exe").exists()
    assert not (env["data"] / ".backtest.lock").exists()


def test_symbol_with_newline_rejected(env):
    setup(env)
    with pytest.raises(SystemExit) as e:
        cli.main([str(env["ea"]), "--symbol", "EURUSD\n[StartUp]", "--period", "H1", "--from", "2026-10-01",
                  "--to", "2026-11-01", "--tester-path", str(env["tester"]), "--config", str(env["cfg"])])
    assert e.value.code == 2


def test_run_override_differing_from_setup_exit2(env, monkeypatch, capsys):
    setup(env)
    other = env["tmp"] / "other-data"
    other.mkdir()
    monkeypatch.setattr(cli, "locate_terminal", lambda **kw: TerminalPaths(env["install"], env["install"] / "metaeditor64.exe", other))
    assert bt(env, "--data-path", str(other)) == 2
    assert "--setup" in capsys.readouterr().err


def test_run_override_matching_setup_is_fine(env):
    setup(env)
    assert bt(env, "--data-path", str(env["data"])) == 0


def test_build_check_waits_for_the_lock(env, capsys):
    setup(env)
    exe = env["install"] / "terminal64.exe"
    st = exe.stat()
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    with ws.tester_lock(env["tester"]):
        assert bt(env) == 2
    assert "another backtest is running" in capsys.readouterr().err


def test_ea_inside_live_experts_keeps_its_folder_and_siblings(env):
    project = env["data"] / "MQL5" / "Experts" / "Project"
    project.mkdir(parents=True)
    (project / "X.ex5").write_bytes(b"lib")  # #import "X.ex5" searches the EA's own folder
    env["ea"] = project / "MyEA.ex5"
    env["ea"].write_bytes(b"EX5")
    assert bt(env) == 0
    assert env["inis"][-1]["Expert"] == "Project\\MyEA.ex5"
    assert (env["tester"] / "MQL5" / "Experts" / "Project" / "X.ex5").is_file()
    assert not (env["tester"] / "MQL5" / "Experts" / "Agent" / "MyEA.ex5").exists()


def test_ea_outside_live_tree_is_staged_after_mirroring(env):
    assert bt(env) == 0
    assert (env["tester"] / "MQL5" / "Experts" / "Agent" / "MyEA.ex5").is_file()


def _flaky(env, monkeypatch, *, codes):
    """A terminal that exits with codes[i] and writes the report only from the second launch."""
    real = cli.run_supervised

    def run(cmdline, **kw):
        i = len(env["calls"])
        env["write"] = i >= 1
        real(cmdline, **kw)
        return codes[min(i, len(codes) - 1)]

    monkeypatch.setattr(cli, "run_supervised", run)


def test_clean_exit_without_report_is_retried_once(env, monkeypatch, capsys):
    setup(env)
    capsys.readouterr()
    _flaky(env, monkeypatch, codes=[0])
    assert bt(env) == 0
    assert len(env["calls"]) == 2
    cap = capsys.readouterr()
    assert "net_profit:" in cap.out and "running it once more" in cap.err


def test_failed_exit_without_report_is_not_retried(env, monkeypatch, capsys):
    setup(env)
    _flaky(env, monkeypatch, codes=[3294954941])
    assert bt(env) == 2
    assert len(env["calls"]) == 1


def test_no_report_after_retry_exit2(env, capsys):
    setup(env)
    env["write"] = False
    assert bt(env) == 2
    assert len(env["calls"]) == 2
    assert "no report" in capsys.readouterr().err


def test_single_run_summary_starts_with_settings(env, capsys):
    setup(env)
    capsys.readouterr()
    assert bt(env, "--deposit", "2500.5", "--currency", "EUR", "--leverage", "30") == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "settings: EURUSD H1 2026-10-01..2026-11-01 model=ohlc deposit=2500.5 EUR leverage=1:30"


def test_settings_deposit_matches_the_ini(env, capsys):
    setup(env)
    capsys.readouterr()
    assert bt(env, "--deposit", "2500.567") == 0
    assert env["inis"][-1]["Deposit"] == "2500.57"
    assert "deposit=2500.57 USD" in capsys.readouterr().out.splitlines()[0]


def test_single_run_writes_json_and_prints_path(env, capsys):
    env["single"] = "single_deals.htm"
    assert bt(env) == 0
    out = capsys.readouterr().out
    path = Path(re.search(r"^json: (.+)$", out, re.M)[1])
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["kind"] == "single" and doc["settings"]["symbol"] == "EURUSD" and doc["journal"]["started"] is True
    assert doc["settings"]["deposit"] == 10000.0 and doc["settings"]["leverage"] == 100
    assert path.parent == env["tester"] / "reports" and path.name.endswith("Z-MyEA.json")
    assert out.index("json: ") < out.index("report: ")
    assert "journal:" not in out


def test_json_flag_prints_only_the_document(env, capsys):
    env["single"] = "single_deals.htm"
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["deals"]) == 97


def test_failinit_exit2_with_journal(env, capsys):
    env["single"], env["journal"] = "single_failinit.htm", "failinit.log"
    assert bt(env) == 2
    err = capsys.readouterr().err
    assert "EA failed to start" in err and "OnInit returns non-zero code 1" in err and "journal:" in err


def test_crash_exit2_json_still_written_and_printed(env, capsys):
    env["single"], env["journal"] = "single_arrayerr.htm", "arrayerr.log"
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json") == 2
    cap = capsys.readouterr()
    assert json.loads(cap.out)["journal"]["crashed"] is True
    assert "EA hit a runtime error" in cap.err and "array out of range" in cap.err
    assert list((env["tester"] / "reports").glob("*.json"))


def test_zero_trades_shows_journal_block_exit0(env, capsys):
    env["single"], env["journal"] = "single_failinit.htm", "notrade.log"
    env["ea"] = env["tmp"] / "NoTrade.ex5"  # journal lines are matched by the EA's file name
    env["ea"].write_bytes(b"EX5")
    assert bt(env) == 0
    out = capsys.readouterr().out
    assert "journal:" in out and out.index("journal:") < out.index("report: ")


def test_optimization_journal_never_changes_exit(env, capsys):
    env["journal"] = "failinit.log"
    s = write_set(env, "MovingPeriod=12||6||2||30||Y\nMovingShift=6||0||2||10||Y\n")
    assert bt(env, "--optimize", "full", "--set", s) == 0
    doc = json.loads(next((env["tester"] / "reports").glob("*.json")).read_text(encoding="utf-8"))
    assert doc["kind"] == "optimization" and doc["journal"]["started"] is None
    assert doc["settings"]["criterion"] == "balance" and doc["passes"][0]["pass"] == 68


def test_read_prints_json_and_writes_nothing(capsys, tmp_path):
    report = tmp_path / "r.htm"
    shutil.copy(FIX / "single_deals.htm", report)
    assert cli.main(["--read", str(report)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["journal"] is None and doc["settings"]["symbol"] == "EURUSD"
    assert doc["settings"]["from"] == "2026-09-01" and doc["settings"]["deposit"] == 10000.0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.htm"]


def test_read_optimization_xml_uses_forward_file(capsys, tmp_path):
    shutil.copy(FIX / "opt_full_fwd.xml", tmp_path / "o.xml")
    shutil.copy(FIX / "opt_full_fwd.forward.xml", tmp_path / "o.forward.xml")
    assert cli.main(["--read", str(tmp_path / "o.xml")]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["kind"] == "optimization" and doc["passes"][0]["forward"]["result"] == 10133.20


def test_read_with_ea_is_an_error(env):
    with pytest.raises(SystemExit) as e:
        cli.main([str(env["ea"]), "--read", str(FIX / "single_deals.htm")])
    assert e.value.code == 2


def test_unreadable_journal_keeps_a_finished_run(env, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(cli, "read_new", boom)
    setup(env)
    capsys.readouterr()
    assert bt(env) == 0
    cap = capsys.readouterr()
    assert "net_profit:" in cap.out and "could not read the tester log" in cap.err
    doc = json.loads(next((env["tester"] / "reports").glob("*.json")).read_text(encoding="utf-8"))
    assert doc["journal"] is None


def test_journal_read_while_lock_held(env, monkeypatch):
    real = cli.read_new

    def check(tester, before, logs=None):
        with pytest.raises(ws.LockHeld):
            with ws.tester_lock(tester):
                pass
        return real(tester, before, logs)

    monkeypatch.setattr(cli, "read_new", check)
    assert bt(env) == 0


def test_json_deposit_matches_the_ini(env, capsys):
    setup(env)
    capsys.readouterr()
    assert bt(env, "--deposit", "2500.567", "--json") == 0
    assert json.loads(capsys.readouterr().out)["settings"]["deposit"] == 2500.57


def test_failed_run_text_mode_names_json_and_report(env, capsys):
    env["single"], env["journal"] = "single_failinit.htm", "failinit.log"
    setup(env)
    capsys.readouterr()
    assert bt(env) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert re.search(r"^json: .+Z-MyEA\.json$", cap.err, re.M) and re.search(r"^report: .+Z-MyEA\.htm$", cap.err, re.M)


OPT_SET = "MaximumRisk=0.02\nDecreaseFactor=3\nMovingPeriod=12||6||2||30||Y\nMovingShift=6||0||2||10||Y\n"


def test_out_copies_report_and_json(env, capsys):
    out = env["tmp"] / "out"
    assert bt(env, "--out", str(out)) == 0
    htm, js = list(out.glob("*.htm")), list(out.glob("*.json"))
    assert len(htm) == 1 and len(js) == 1
    assert json.loads(js[0].read_text(encoding="utf-8"))["report"] == str(htm[0])
    text = capsys.readouterr().out
    assert f"json: {js[0]}" in text and f"report: {htm[0]}" in text


def test_out_optimization_copies_back_and_forward(env):
    out = env["tmp"] / "out"
    assert bt(env, "--optimize", "full", "--set", write_set(env, OPT_SET), "--out", str(out)) == 0
    names = sorted(p.name for p in out.iterdir())
    assert [n.endswith(".forward.xml") for n in names].count(True) == 1
    assert [n.endswith(".xml") for n in names].count(True) == 2 and any(n.endswith(".json") for n in names)


def test_out_failed_start_still_delivers_named_files(env, capsys):
    env["single"], env["journal"] = "single_failinit.htm", "failinit.log"
    out = env["tmp"] / "out"
    assert bt(env, "--out", str(out)) == 2
    named = [ln.split(": ", 1)[1] for ln in capsys.readouterr().err.splitlines() if ln.startswith(("json: ", "report: "))]
    assert len(named) == 2 and all(Path(p).is_file() and Path(p).parent == out for p in named)


def test_out_no_report_copies_only_the_error_json(env):
    env["write"] = False
    out = env["tmp"] / "out"
    assert bt(env, "--out", str(out)) == 2
    [doc] = out.iterdir()
    assert doc.suffix == ".json" and json.loads(doc.read_text(encoding="utf-8"))["error"]


@pytest.mark.parametrize("extra", [["--setup"], ["--read", "x.htm"]])
def test_out_with_setup_or_read_is_usage_error(env, extra):
    with pytest.raises(SystemExit) as e:
        cli.main([*extra, "--out", str(env["tmp"] / "o"), "--tester-path", str(env["tester"])])
    assert e.value.code == 2


def _hold(tester, secs, held):
    with ws.tester_lock(tester):
        held.set()
        time.sleep(secs)


def _held(tester, secs):
    """A thread holding the tester lock for `secs`; returns once it has the lock."""
    held = threading.Event()
    t = threading.Thread(target=_hold, args=(tester, secs, held))
    t.start()
    held.wait()
    return t


def test_wait_runs_after_lock_released_exit0(env, capsys):
    setup(env)
    t = _held(env["tester"], 1.5)
    assert bt(env, "--wait") == 0
    t.join()
    assert capsys.readouterr().err.count("waiting for another backtest to finish...") == 1


def test_optimization_clears_mt5_cache_before_run(env):
    # An identical re-run is served from Tester/cache without a forward report (seen 2026-11-20).
    setup(env)
    cache = env["tester"] / "Tester" / "cache"
    cache.mkdir(parents=True)
    (cache / "EA.EURUSD.H1.1.2.10.ABC.opt").write_bytes(b"cached")
    (cache / "EA.EURUSD.H1.1_2.1.DEF.tst").write_bytes(b"single")
    assert bt(env, "--optimize", "full", "--set", write_set(env, OPT_SET)) == 0
    assert not any(cache.glob("*.opt")) and any(cache.glob("*.tst"))


def test_unreadable_report_shows_the_journal_errors(env, monkeypatch, capsys):
    # A real-ticks run without history writes 'n/a' cells; the reason is in the tester log.
    env["journal"] = "failinit.log"

    def bad(_):
        raise cli.ReportError("not a number in report: 'n/a'")

    monkeypatch.setattr(cli, "parse_single_html", bad)
    assert bt(env) == 2
    err = capsys.readouterr().err
    assert "not a number in report: 'n/a'" in err and "tester stopped because OnInit" in err


def test_out_unusable_dir_fails_before_the_run(env, capsys):
    setup(env)
    not_a_dir = env["tmp"] / "file"
    not_a_dir.write_text("x")
    assert bt(env, "--out", str(not_a_dir)) == 2
    assert env["calls"] == []  # the terminal never started


def test_wait_through_an_automatic_refresh_sees_the_setup(env):
    # A refresh deletes origin.json while it copies; a queued run must check after the lock, not before.
    setup(env)
    origin = env["tester"] / "origin.json"
    saved = origin.read_bytes()
    locked = threading.Event()

    def refresh():
        with ws.tester_lock(env["tester"]):
            origin.unlink()
            locked.set()
            time.sleep(1.0)
            origin.write_bytes(saved)

    t = threading.Thread(target=refresh)
    t.start()
    locked.wait()
    assert bt(env, "--wait", setup_first=False) == 0
    t.join()


def test_out_into_the_testers_own_reports_folder(env, capsys):
    setup(env)
    reports = env["tester"] / "reports"
    assert bt(env, "--out", str(reports)) == 0
    assert any(reports.glob("*.json")) and "json: " in capsys.readouterr().out


def test_out_keeps_an_unreadable_report(env, monkeypatch, capsys):
    out = env["tmp"] / "out"

    def bad(_):
        raise cli.ReportError("not a number in report: 'n/a'")

    monkeypatch.setattr(cli, "parse_single_html", bad)
    assert bt(env, "--out", str(out)) == 2
    htm = list(out.glob("*.htm"))
    assert len(htm) == 1 and f"report: {htm[0]}" in capsys.readouterr().err


def test_out_keeps_the_back_report_when_the_forward_one_is_missing(env, capsys):
    out = env["tmp"] / "out"
    original = cli.run_supervised

    def no_forward(cmdline, **kw):
        rc = original(cmdline, **kw)
        for f in env["tester"].glob("reports/*.forward.xml"):
            f.unlink()
        return rc

    cli.run_supervised = no_forward
    try:
        assert bt(env, "--optimize", "full", "--set", write_set(env, OPT_SET), "--out", str(out)) == 2
    finally:
        cli.run_supervised = original
    xml = [p for p in out.glob("*.xml") if not p.name.endswith(".forward.xml")]
    assert len(xml) == 1 and f"report: {xml[0]}" in capsys.readouterr().err


def test_tester_agent_update_alone_triggers_a_refresh(env, capsys):
    # LiveUpdate can move metatester64.exe while terminal64.exe stays (the old Wine pin did exactly this).
    agent = env["install"] / "metatester64.exe"
    agent.write_bytes(b"agent v1")
    setup(env)
    agent.write_bytes(b"agent v2, newer build")
    assert bt(env) == 0
    assert "MT5 was updated; refreshed the tester install" in capsys.readouterr().err
    assert (env["tester"] / "metatester64.exe").read_bytes() == b"agent v2, newer build"


def _term_log(lines):
    """Terminal log lines (code, level, time, source, message) as MT5 writes them: UTF-16 with a BOM."""
    return "\ufeff" + "".join(f"AB\t{lvl}\t10:00:00.000\t{src}\t{msg}\r\n" for lvl, src, msg in lines)


NO_TICKS = [
    (0, "Tester", 'EURUSD: "bases\\Broker-Demo\\ticks\\EURUSD\\202611.tkc" download'),
    (1, "Network", "'123': connection to Broker-Demo lost"),
    (0, "Tester", "EURUSD: preliminary downloading of history ticks canceled"),
    (3, "Tester", "no history data, stop testing"),
]


def _unreadable_run(env, monkeypatch, lines):
    """A run whose report is all 'n/a', with these lines added to the tester's terminal log."""
    original = env.setdefault("fake_run", cli.run_supervised)  # not a previous call's wrapper

    def run(cmdline, **kw):
        rc = original(cmdline, **kw)
        log = env["tester"] / "Tester" / "logs" / "20261120.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        text = _term_log(lines)
        with open(log, "ab") as f:  # the terminal log collects every run of the day
            f.write((text if f.tell() == 0 else text.lstrip("\ufeff")).encode("utf-16-le"))
        return rc

    def bad(_):
        raise cli.ReportError("not a number in report: 'n/a'")

    monkeypatch.setattr(cli, "run_supervised", run)
    monkeypatch.setattr(cli, "parse_single_html", bad)


def test_unreadable_report_leads_with_the_testers_reason(env, monkeypatch, capsys):
    _unreadable_run(env, monkeypatch, NO_TICKS)
    assert bt(env) == 2
    first = capsys.readouterr().err.splitlines()[0]
    assert first == ("no history data, stop testing (EURUSD: preliminary downloading of history ticks canceled; "
                     "connection to the trade server was lost)")


def test_unreadable_report_json_has_the_error(env, monkeypatch, capsys):
    _unreadable_run(env, monkeypatch, NO_TICKS)
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json") == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["kind"] == "single" and doc["error"].startswith("no history data")
    assert doc["settings"]["symbol"] == "EURUSD" and doc["report"].endswith(".htm")
    saved = next((env["tester"] / "reports").glob("*.json"))
    assert json.loads(saved.read_text(encoding="utf-8"))["error"] == doc["error"]


def test_failed_run_log_tail_has_only_this_runs_lines(env, monkeypatch, capsys):
    _unreadable_run(env, monkeypatch, [(0, "Tester", "GBPUSD: lines of an earlier run")])
    assert bt(env) == 2  # the earlier run
    _unreadable_run(env, monkeypatch, [(0, "Tester", "EURUSD: this run")])
    capsys.readouterr()
    assert bt(env) == 2
    err = capsys.readouterr().err
    assert "EURUSD: this run" in err and "earlier run" not in err


def test_no_report_json_flag_prints_the_error_document(env, capsys):
    env["write"] = False
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json") == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["error"].startswith("no report written") and doc["kind"] == "single"


def test_set_typo_json_has_the_error(env, capsys):
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json", "--set", write_set(env, "MaximumRisk=0.02\nBogusInput=7\n")) == 2
    doc = json.loads(capsys.readouterr().out)
    assert "BogusInput" in doc["error"] and doc["metrics"]


def test_successful_run_json_has_null_error(env, capsys):
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json") == 0
    assert json.loads(capsys.readouterr().out)["error"] is None


def test_optimization_set_problem_json_has_the_error(env, capsys):
    s = write_set(env, "BogusInput=1||1||1||3||Y\nMovingPeriod=12||6||2||30||Y\n")
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json", "--optimize", "full", "--set", s) == 2
    assert "BogusInput" in json.loads(capsys.readouterr().out)["error"]


def test_failed_start_with_a_set_leads_with_the_start_failure(env, capsys):
    env["single"], env["journal"] = "single_failinit.htm", "failinit.log"
    assert bt(env, "--set", write_set(env, "BogusInput=7\n")) == 2
    assert capsys.readouterr().err.startswith("EA failed to start:")


def test_non_finite_numbers_are_written_as_null(env, monkeypatch, capsys):
    real = cli.parse_single_html

    def inf(raw):
        r = real(raw)
        r.metrics["profit_factor"] = float("inf")
        return r

    monkeypatch.setattr(cli, "parse_single_html", inf)
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json") == 0
    out = capsys.readouterr().out
    assert "Infinity" not in out and json.loads(out)["metrics"]["profit_factor"] is None
    saved = next((env["tester"] / "reports").glob("*.json")).read_text(encoding="utf-8")
    assert "Infinity" not in saved


def test_read_forward_xml_is_a_one_line_error(capsys, tmp_path):
    shutil.copy(FIX / "opt_full_fwd.forward.xml", tmp_path / "o.forward.xml")
    assert cli.main(["--read", str(tmp_path / "o.forward.xml")]) == 2
    err = capsys.readouterr().err
    assert "o.xml" in err and len(err.strip().splitlines()) == 1


def test_read_with_run_flags_is_an_error(tmp_path):
    shutil.copy(FIX / "single_deals.htm", tmp_path / "r.htm")
    with pytest.raises(SystemExit) as e:
        cli.main(["--read", str(tmp_path / "r.htm"), "--symbol", "EURUSD"])
    assert e.value.code == 2


def test_timeout_writes_and_prints_the_error_document(env, capsys):
    setup(env)
    env["write"] = "timeout"
    capsys.readouterr()
    assert bt(env, "--json", "--timeout", "5") == 2
    doc = json.loads(capsys.readouterr().out)
    assert "did not finish" in doc["error"]
    assert json.loads(next((env["tester"] / "reports").glob("*.json")).read_text(encoding="utf-8"))["error"]


def test_failure_in_text_mode_names_the_json(env, capsys):
    env["write"] = False
    assert bt(env) == 2
    path = Path(re.search(r"^json: (.+)$", capsys.readouterr().err, re.M)[1])
    assert json.loads(path.read_text(encoding="utf-8"))["error"].startswith("no report written")


def test_unreadable_terminal_log_keeps_a_finished_run(env, monkeypatch):
    def broken(*a, **kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(cli, "log_tail", broken)
    assert bt(env) == 0


def test_optimization_report_with_na_cells_gives_the_error_document(env, monkeypatch, capsys):
    def bad(*a):
        raise cli.ReportError("not a number in report: 'n/a'")

    monkeypatch.setattr(cli, "merge_passes", bad)
    setup(env)
    capsys.readouterr()
    assert bt(env, "--json", "--optimize", "full", "--set", write_set(env, OPT_SET)) == 2
    assert json.loads(capsys.readouterr().out)["kind"] == "optimization"


def _ea_log(tmp, name, n, prefix):
    """An agent log with n Print lines from MyEA, UTF-16 like the real one."""
    text = "".join(f"CS\t0\t00:00:00.000\tMyEA (EURUSD,H1)\t2026.01.01 00:00:00   {prefix} {i}\r\n" for i in range(n))
    path = tmp / name
    path.write_bytes(text.encode("utf-16-le"))
    return str(path)


def test_ea_log_holds_every_line_of_this_run_only(env):
    setup(env)
    log = env["tester"] / "Tester" / "Agent-127.0.0.1-3000" / "logs" / "20261120.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(Path(_ea_log(env["tmp"], "old.log", 5, "old")).read_bytes())  # an earlier run today
    env["journal"] = _ea_log(env["tmp"], "new.log", 300, "bar")
    out = env["tmp"] / "out"
    assert bt(env, "--out", str(out)) == 0
    [js] = out.glob("*.json")
    j = json.loads(js.read_text(encoding="utf-8"))["journal"]
    assert len(j["ea_lines"]) == 200
    ea_log = Path(j["ea_log"])
    assert ea_log.parent == out and ea_log.name == js.name.replace(".json", ".ea.log")
    lines = ea_log.read_text(encoding="utf-8").splitlines()
    assert lines == [f"2026.01.01 00:00:00   bar {i}" for i in range(300)]


def test_ea_log_written_when_the_ea_fails_to_start(env):
    env["single"], env["journal"] = "single_failinit.htm", "failinit.log"
    env["ea"] = env["tmp"] / "FailInit.ex5"
    env["ea"].write_bytes(b"EX5")
    out = env["tmp"] / "out"
    assert bt(env, "--out", str(out)) == 2
    [ea_log] = out.glob("*.ea.log")
    assert ea_log.read_text(encoding="utf-8")


def test_retried_run_ea_log_keeps_only_the_last_attempt(env, monkeypatch):
    setup(env)
    env["journal"] = _ea_log(env["tmp"], "new.log", 3, "bar")
    real = cli.run_supervised

    def run(cmdline, **kw):  # the first launch runs the test but leaves no report
        real(cmdline, **kw)
        if len(env["calls"]) == 1:
            report = env["tester"] / env["inis"][0]["Report"].replace("\\", "/")
            report.with_name(report.name + ".htm").unlink()
        return 0

    monkeypatch.setattr(cli, "run_supervised", run)
    out = env["tmp"] / "out"
    assert bt(env, "--out", str(out)) == 0 and len(env["calls"]) == 2
    [ea_log] = out.glob("*.ea.log")
    assert ea_log.read_text(encoding="utf-8").splitlines() == [f"2026.01.01 00:00:00   bar {i}" for i in range(3)]


def test_optimization_writes_no_ea_log(env):
    out = env["tmp"] / "out"
    assert bt(env, "--optimize", "full", "--set", write_set(env, OPT_SET), "--out", str(out)) == 0
    assert not list(out.glob("*.ea.log"))
    assert json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))["journal"]["ea_log"] is None
