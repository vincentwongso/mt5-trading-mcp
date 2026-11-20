import argparse
from datetime import date

import pytest

from mt5_mcp.mql5.tester import (
    RunSpec,
    SetFile,
    build_ini,
    check_inputs,
    parse_forward,
    parse_set,
    write_ini,
)


def _spec(**kw):
    base = dict(
        expert="Agent\\MyEA.ex5", symbol="EURUSD.z", period="H1",
        date_from=date(2026, 10, 1), date_to=date(2026, 11, 1),
        deposit=10000.0, currency="USD", leverage=100, model="ohlc",
        optimize=None, criterion="balance", forward="1/3", set_name=None,
        report="reports\\x",
    )
    base.update(kw)
    return RunSpec(**base)


def _lines(text):
    return text.splitlines()


def test_build_ini_single_run():
    lines = _lines(build_ini(_spec()))
    assert lines[0] == "[Tester]"
    for want in ("Expert=Agent\\MyEA.ex5", "Symbol=EURUSD.z", "Period=H1", "Model=1",
                 "FromDate=2026.10.01", "ToDate=2026.11.01", "Deposit=10000", "Currency=USD",
                 "Leverage=100", "Optimization=0", "ForwardMode=0", "Report=reports\\x",
                 "ReplaceReport=1", "ShutdownTerminal=1", "[Experts]", "AllowLiveTrading=0", "Enabled=0"):
        assert want in lines
    assert not any(line.startswith("ExpertParameters=") for line in lines)


def test_build_ini_without_disable_live_has_no_experts_section():
    assert "[Experts]" not in _lines(build_ini(_spec(), disable_live=False))


def test_build_ini_optimize_genetic_forward_third():
    lines = _lines(build_ini(_spec(optimize="genetic", set_name="r.set")))
    for want in ("Optimization=2", "OptimizationCriterion=0", "ForwardMode=2", "ExpertParameters=r.set"):
        assert want in lines


def test_build_ini_forward_date():
    lines = _lines(build_ini(_spec(optimize="full", forward="2026-10-20", criterion="sharpe")))
    for want in ("Optimization=1", "OptimizationCriterion=5", "ForwardMode=4", "ForwardDate=2026.10.20"):
        assert want in lines


def test_build_ini_forward_ignored_for_single_run():
    lines = _lines(build_ini(_spec(forward="1/3")))
    assert "ForwardMode=0" in lines
    assert not any(line.startswith("ForwardDate=") for line in lines)


def test_build_ini_real_ticks_model():
    assert "Model=4" in _lines(build_ini(_spec(model="real")))


def test_write_ini_utf16le_bom_crlf(tmp_path):
    p = tmp_path / "t.ini"
    write_ini(p, "[Tester]\nSymbol=X\n")
    raw = p.read_bytes()
    assert raw.startswith(b"\xff\xfe")
    assert raw[2:].decode("utf-16-le") == "[Tester]\r\nSymbol=X\r\n"


@pytest.mark.parametrize("value", ["off", "1/2", "1/3", "1/4", "2026-10-20"])
def test_parse_forward_accepts(value):
    assert parse_forward(value) == value


@pytest.mark.parametrize("value", ["1/5", "2026-13-01", "", "third"])
def test_parse_forward_rejects_garbage(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_forward(value)


SET_TEXT = "; saved by agent\r\nMaximumRisk=0.02\r\nMovingPeriod=12||6||2||30||Y\r\nMovingShift=6||0||2||10||N\r\n\r\n"


def test_parse_set_fixed_optimized_and_n_flag():
    want = SetFile(fixed={"MaximumRisk": "0.02", "MovingShift": "6"}, optimized={"MovingPeriod": "12"})
    assert parse_set(SET_TEXT.encode("utf-8")) == want
    assert parse_set(b"\xff\xfe" + SET_TEXT.encode("utf-16-le")) == want


def test_check_inputs_float_equal():
    s = SetFile(fixed={"DecreaseFactor": "3"}, optimized={})
    assert check_inputs(s, {"DecreaseFactor": "3.0"}, optimized_names=None) is None


def test_check_inputs_value_mismatch():
    s = SetFile(fixed={"Lots": "0.1"}, optimized={})
    assert "Lots" in check_inputs(s, {"Lots": "0.2"}, optimized_names=None)


def test_check_inputs_unknown_name():
    s = SetFile(fixed={"BogusInput": "7"}, optimized={})
    msg = check_inputs(s, {"Lots": "0.1"}, optimized_names=None)
    assert msg is not None and "BogusInput" in msg


def test_check_inputs_single_run_optimized_against_value():
    s = SetFile(fixed={}, optimized={"MovingPeriod": "12"})
    assert check_inputs(s, {"MovingPeriod": "12"}, optimized_names=None) is None
    assert check_inputs(s, {"MovingPeriod": "6"}, optimized_names=None) is not None


def test_check_inputs_optimized_names_mismatch():
    s = SetFile(fixed={}, optimized={"MovingPeriod": "12", "MovingShift": "6"})
    assert check_inputs(s, {}, optimized_names=["MovingShift", "MovingPeriod"]) is None
    assert check_inputs(s, {}, optimized_names=["MovingPeriod"]) is not None


def test_check_inputs_compares_non_numeric_case_insensitively():
    s = SetFile(fixed={"UseFilter": "False", "Note": "abc def"}, optimized={})
    assert check_inputs(s, {"UseFilter": "false", "Note": "abc def"}, optimized_names=None) is None
    assert check_inputs(s, {"UseFilter": "false", "Note": "abc"}, optimized_names=None) is not None
