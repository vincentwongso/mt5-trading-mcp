"""doctor CLI smoke check."""

from __future__ import annotations

from datetime import datetime, timezone

from mt5_mcp.cli.doctor import run_doctor
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def test_doctor_all_green(capsys):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = (FakeSymbolInfo(name="EURUSD"),)

    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD")
    captured = capsys.readouterr()
    assert rc == 0
    assert "[PASS]" in captured.out
    assert "[FAIL]" not in captured.out


def test_doctor_reports_disconnection(capsys):
    fake = FakeMT5()
    fake._terminal_info = None
    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD")
    captured = capsys.readouterr()
    assert rc != 0
    assert "[FAIL]" in captured.out
