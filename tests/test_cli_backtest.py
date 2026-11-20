"""`mt5-mcp backtest` end to end, with the terminal and discovery faked."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

import mt5_mcp.cli.backtest as cli
from mt5_mcp.mql5 import workspace as ws
from mt5_mcp.mql5.compiler import CompileTimeout
from mt5_mcp.mql5.terminal import TerminalPaths

FIX = Path(__file__).parent / "fixtures" / "mql5" / "reports"


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
             "write": True, "calls": [], "inis": []}

    def fake_run(cmdline, *, timeout_s, label, kill=None):
        state["calls"].append(cmdline)
        ini = _ini(cmdline)
        state["inis"].append(ini)
        if state["write"] == "timeout":
            raise CompileTimeout(f"{label} did not finish in {timeout_s:g}s; killed.")
        if state["write"]:
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
    base = [str(env["ea"]), "--symbol", "EURUSD.z", "--period", "H1", "--from", "2026-10-01",
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
    assert lines[0].split()[:3] == ["rank", "pass", "fwd_result"]
    assert lines[1].split()[:2] == ["1", "68"]
    assert len(lines) == 1 + 3 + 1


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


def test_no_report_exit2_with_log_tail(env, capsys):
    assert bt(env) == 0  # leaves an older report behind
    (env["tester"] / "logs").mkdir(exist_ok=True)
    (env["tester"] / "logs" / "20261120.log").write_bytes("tester EX5 not found".encode("utf-16"))
    env["write"] = False
    capsys.readouterr()
    assert bt(env) == 2
    err = capsys.readouterr().err
    assert "no report" in err and "== " in err and "EX5 not found" in err


def test_not_set_up_exit2(env, capsys):
    assert bt(env, setup_first=False) == 2
    assert "--setup" in capsys.readouterr().err


def test_build_mismatch_exit2(env, capsys):
    setup(env)
    exe = env["install"] / "terminal64.exe"
    st = exe.stat()
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert bt(env) == 2
    assert "re-run mt5-mcp backtest --setup" in capsys.readouterr().err


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
