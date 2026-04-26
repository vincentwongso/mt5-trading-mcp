"""doctor CLI smoke check."""

from __future__ import annotations

from datetime import datetime, timezone

from mt5_mcp.cli.doctor import run_doctor
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def test_doctor_all_green(capsys, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = (FakeSymbolInfo(name="EURUSD"),)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD", config_path=cfg)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[PASS]" in captured.out
    assert "[FAIL]" not in captured.out


def test_doctor_reports_disconnection(capsys, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = None
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD", config_path=cfg)
    captured = capsys.readouterr()
    assert rc != 0
    assert "[FAIL]" in captured.out


def test_doctor_smoke_trade_round_trip(capsys, tmp_path, frozen_utc):
    """When --smoke-trade is enabled, doctor places + closes a micro-lot order."""
    from tests.fakes import (
        FakeAccountInfo, FakeMT5, FakeOrderSendResult, FakePosition,
        FakeSymbolInfo, FakeTerminalInfo, FakeTick, POSITION_TYPE_BUY,
        TRADE_RETCODE_DONE,
    )

    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo(currency="USD", leverage=100)
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    fake._symbols_get = (FakeSymbolInfo(name="EURUSD"),)
    # The place_order RPC returns ticket 12345 with the requested 0.01 vol.
    # That ticket then needs to exist in positions_get when close_position runs.
    fake._order_send = FakeOrderSendResult(
        retcode=TRADE_RETCODE_DONE, order=12345, deal=99,
        volume=0.01, price=1.0824,
    )
    fake._positions_get = (
        FakePosition(ticket=12345, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=0.01, price_open=1.0824, price_current=1.0824),
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\nauto_approve_notional = "1000000"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD",
                    config_path=cfg, smoke_trade=True)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[PASS] place_order ticket=12345" in captured.out
    assert "[PASS] close_position ticket=12345" in captured.out


def test_doctor_smoke_trade_off_by_default(capsys, tmp_path, frozen_utc):
    """Without --smoke-trade, no order_send happens."""
    from tests.fakes import FakeAccountInfo, FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick

    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = (FakeSymbolInfo(name="EURUSD"),)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD", config_path=cfg)
    assert rc == 0
    assert len(fake.order_send_calls) == 0  # smoke trade NOT executed
