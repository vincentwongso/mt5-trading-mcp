"""`mt5-mcp compile` end to end, with MetaEditor and discovery faked."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

import mt5_mcp.cli.compile as cli
from mt5_mcp.mql5.compiler import CompileTimeout
from mt5_mcp.mql5.terminal import LocateError, TerminalPaths

FIX = Path(__file__).parent / "fixtures" / "mql5"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake data folder, a config file, and a recorder for MetaEditor runs."""
    data = tmp_path / "data"
    (data / "MQL5").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    cfg = tmp_path / "config.toml"
    cfg.write_text("[mt5]\nterminal_path = ''\n")
    monkeypatch.setattr(cli, "locate_terminal", lambda **kw: TerminalPaths(tmp_path, tmp_path / "metaeditor64.exe", data))
    state = {"log": "clean.log", "write_ex5": True, "cmdlines": [], "log_dirs": []}

    def fake_run(cmdline, *, timeout_s):
        state["cmdlines"].append(cmdline)
        log = Path(re.search(r'/log:"([^"]+)"', cmdline)[1])
        state["log_dirs"].append(log.parent)
        shutil.copy(FIX / "logs" / state["log"], log)
        src = Path(re.search(r'/compile:"([^"]+)"', cmdline)[1])
        if state["write_ex5"]:
            # Like MetaEditor: Shared Projects builds land in MQL5/<Kind>/Shared Projects/.
            mql5 = state["data"] / "MQL5"
            out = src.with_suffix(".ex5")
            if src.is_relative_to(mql5 / "Shared Projects"):
                out = mql5 / "Experts" / out.relative_to(mql5)
                out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"EX5")
        return 1

    monkeypatch.setattr(cli, "run_metaeditor", fake_run)
    state.update(data=data, work=work, cfg=cfg)
    return state


def run(env, name, *extra, src_dir=None):
    src_dir = src_dir or env["work"]
    src = src_dir / name
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "src" / name, src)
    return cli.main([str(src), "--config", str(env["cfg"]), *extra])


def test_clean_build_installs_to_agent_folder(env, capsys):
    assert run(env, "clean_ea.mq5") == 0
    out, err = capsys.readouterr()
    target = env["data"] / "MQL5" / "Experts" / "Agent" / "clean_ea.ex5"
    assert target.read_bytes() == b"EX5"
    assert f"installed: {target}" in out
    assert "Result: 0 errors, 0 warnings" in out
    assert f"data folder: {env['data']}" in err


def test_inc_points_at_data_mql5(env):
    run(env, "clean_ea.mq5")
    assert f'/inc:"{env["data"] / "MQL5"}"' in env["cmdlines"][0]


def test_errors_exit_1_and_print_diagnostic(env, capsys):
    env["log"], env["write_ex5"] = "errors.log", False
    assert run(env, "broken_ea.mq5") == 1
    out = capsys.readouterr().out
    assert "broken_ea.mq5:4:4: error 256: undeclared identifier 'foo'" in out
    assert "Result: 1 error, 0 warnings" in out
    assert not (env["data"] / "MQL5" / "Experts").exists()


def test_warnings_still_exit_0(env, capsys):
    env["log"] = "warnings.log"
    assert run(env, "warn_ea.mq5") == 0
    assert ": warning 43: " in capsys.readouterr().out


def test_no_install_flag_skips_copy(env, capsys):
    assert run(env, "clean_ea.mq5", "--no-install") == 0
    assert not (env["data"] / "MQL5" / "Experts").exists()
    assert "installed:" not in capsys.readouterr().out


def test_indicator_detected(env):
    assert run(env, "indicator.mq5") == 0
    assert (env["data"] / "MQL5" / "Indicators" / "Agent" / "indicator.ex5").exists()


def test_kind_flag_overrides_detection(env):
    assert run(env, "clean_ea.mq5", "--kind", "indicator") == 0
    assert (env["data"] / "MQL5" / "Indicators" / "Agent" / "clean_ea.ex5").exists()


def test_library_installs_at_root(env):
    assert run(env, "clean_ea.mq5", "--kind", "library") == 0
    assert (env["data"] / "MQL5" / "Libraries" / "clean_ea.ex5").exists()


def test_source_inside_kind_folder_not_copied(env, capsys):
    experts = env["data"] / "MQL5" / "Experts" / "Mine"
    assert run(env, "clean_ea.mq5", src_dir=experts) == 0
    assert not (env["data"] / "MQL5" / "Experts" / "Agent").exists()
    assert f"installed: {experts / 'clean_ea.ex5'}" in capsys.readouterr().out


def test_shared_project_build_is_already_installed(env, capsys):
    shared = env["data"] / "MQL5" / "Shared Projects" / "proj"
    assert run(env, "clean_ea.mq5", src_dir=shared) == 0
    built = env["data"] / "MQL5" / "Experts" / "Shared Projects" / "proj" / "clean_ea.ex5"
    assert f"installed: {built}" in capsys.readouterr().out
    assert not (env["data"] / "MQL5" / "Experts" / "Agent").exists()


def test_timeout_exit_2_message(env, monkeypatch, capsys):
    def boom(cmdline, *, timeout_s):
        raise CompileTimeout(f"MetaEditor did not finish in {timeout_s:g}s; killed.")
    monkeypatch.setattr(cli, "run_metaeditor", boom)
    assert run(env, "clean_ea.mq5", "--timeout", "3") == 2
    assert "did not finish in 3s" in capsys.readouterr().err


def test_locate_error_exit_2(env, monkeypatch, capsys):
    def nope(**kw):
        raise LocateError("No MetaTrader 5 install found.")
    monkeypatch.setattr(cli, "locate_terminal", nope)
    assert run(env, "clean_ea.mq5") == 2
    assert "No MetaTrader 5 install found." in capsys.readouterr().err


def test_non_mq5_source_exit_2(env, capsys):
    p = env["work"] / "x.mqh"
    p.write_text("")
    assert cli.main([str(p), "--config", str(env["cfg"])]) == 2
    assert "not an .mq5 file" in capsys.readouterr().err


def test_missing_result_line_exit_2(env, tmp_path, capsys):
    (tmp_path / "bad.log").write_bytes("half a log".encode("utf-16"))
    env["log"] = str(tmp_path / "bad.log")  # absolute: replaces the fixture dir in the join
    assert run(env, "clean_ea.mq5") == 2
    assert "half a log" in capsys.readouterr().err


def test_install_oserror_exit_2_after_diagnostics(env, monkeypatch, capsys):
    env["log"] = "warnings.log"

    def denied(*a, **k):
        raise PermissionError("access denied")
    monkeypatch.setattr(cli.shutil, "copy2", denied)
    assert run(env, "warn_ea.mq5") == 2
    out, err = capsys.readouterr()
    assert ": warning 43: " in out
    assert "access denied" in err and "Traceback" not in err


def test_missing_ex5_after_clean_log_exit_2(env, capsys):
    env["write_ex5"] = False
    assert run(env, "clean_ea.mq5") == 2
    assert ".ex5" in capsys.readouterr().err


def test_temp_log_dir_removed(env):
    run(env, "clean_ea.mq5")
    assert env["log_dirs"] and not env["log_dirs"][0].exists()


def test_help_carries_live_reload_warning(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "reloads the new code on that chart" in " ".join(capsys.readouterr().out.split())
