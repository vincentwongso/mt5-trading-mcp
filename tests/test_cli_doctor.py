"""doctor CLI smoke check."""

from __future__ import annotations

from datetime import datetime, timezone

from mt5_mcp.cli.doctor import _resolve_probe_symbol, run_doctor
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


# --- _resolve_probe_symbol ---------------------------------------------------

def test_resolve_picks_first_default_candidate_present():
    # Broker has BTCUSD, EURUSD, USDJPY — picker prefers BTCUSD (top of list).
    assert _resolve_probe_symbol("auto", ["EURUSD", "BTCUSD", "USDJPY"]) == "BTCUSD"


def test_resolve_walks_candidate_list_in_order():
    # No BTCUSD/ETHUSD; XAUUSD comes before USDJPY in the candidate list.
    assert _resolve_probe_symbol("auto", ["USDJPY", "XAUUSD"]) == "XAUUSD"


def test_resolve_falls_back_to_first_symbol_when_no_candidate_matches():
    # Suffixed broker — none of the bare candidate names match.
    assert _resolve_probe_symbol("auto", ["EURUSD.r", "GBPUSD.r"]) == "EURUSD.r"


def test_resolve_returns_none_when_broker_has_no_symbols():
    assert _resolve_probe_symbol("auto", []) is None


def test_resolve_passes_explicit_symbol_through_unchanged():
    # Explicit overrides win even when the symbol is missing on the broker
    # (the user gets a SYMBOL_NOT_FOUND from the probe, by design).
    assert _resolve_probe_symbol("EURUSD.r", ["BTCUSD"]) == "EURUSD.r"
    assert _resolve_probe_symbol("EURUSD.r", []) == "EURUSD.r"


# --- run_doctor end-to-end with auto symbol selection -----------------------

def test_doctor_auto_picks_btcusd_when_available(capsys, tmp_path):
    """Default probe_symbol='auto' picks BTCUSD over EURUSD when both exist."""
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    btc_tick = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=60000.0, ask=60001.0,
    )
    fake._symbol_info["BTCUSD"] = FakeSymbolInfo(name="BTCUSD")
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["BTCUSD"] = btc_tick
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = (FakeSymbolInfo(name="BTCUSD"), FakeSymbolInfo(name="EURUSD"))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, config_path=cfg, check_streaming=False)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[INFO] Auto-selected probe symbol: BTCUSD" in captured.out
    assert "[PASS] get_quote(BTCUSD)" in captured.out
    assert "get_quote(EURUSD)" not in captured.out


def test_doctor_auto_falls_back_to_suffixed_symbol(capsys, tmp_path):
    """Broker that suffixes names (EURUSD.r) — auto picks the broker's first symbol."""
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD.r"] = FakeSymbolInfo(name="EURUSD.r")
    fake._symbol_info_tick["EURUSD.r"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = (FakeSymbolInfo(name="EURUSD.r"),)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, config_path=cfg, check_streaming=False)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[INFO] Auto-selected probe symbol: EURUSD.r" in captured.out
    assert "[PASS] get_quote(EURUSD.r)" in captured.out


def test_doctor_prints_backend_label(fake_mt5, capsys, tmp_path):
    from mt5_mcp.cli.doctor import run_doctor
    run_doctor(mt5_module=fake_mt5, check_streaming=False,
               config_path=tmp_path / "nope.toml")
    out = capsys.readouterr().out
    assert "[INFO] backend: native" in out


def test_doctor_reports_fail_when_ping_returns_ok_false(capsys, tmp_path):
    """ping returning ok=false must produce [FAIL] ping and a non-zero exit code."""
    fake = FakeMT5()
    # Make all three ping layers fail:
    # Layer 1: terminal_info() returns None
    fake._terminal_info = None
    # Layer 2: account_info() returns None (no login available)
    fake._account_info = None
    # Layer 3: _symbol_info_tick is empty by default — no fresh ticks
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, config_path=tmp_path / "nope.toml",
                    check_streaming=False)
    captured = capsys.readouterr()
    assert "[FAIL] ping" in captured.out
    assert "[PASS] ping" not in captured.out
    assert rc != 0


def test_doctor_skips_symbol_probes_when_broker_has_no_symbols(capsys, tmp_path):
    """Empty broker catalogue — skip the symbol-dependent checks gracefully."""
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = ()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )

    rc = run_doctor(mt5_module=fake, config_path=cfg, check_streaming=False)
    captured = capsys.readouterr()
    # No symbols means no symbol-dependent FAILs; rc still 0 because the
    # other checks pass and we explicitly skip rather than fail.
    assert rc == 0
    assert "[SKIP] symbol-dependent probes" in captured.out
    assert "get_quote(" not in captured.out
