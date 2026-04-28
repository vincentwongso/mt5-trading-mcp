"""Market tools: get_quote, get_symbols, get_market_hours, get_rates, calc_margin."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeMT5,
    FakeRate,
    FakeSymbolInfo,
    FakeTerminalInfo,
    FakeTick,
    TIMEFRAME_D1,
    TIMEFRAME_H1,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_quote_returns_bid_ask(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    q = _call(server, "get_quote", symbol="EURUSD")
    assert q.bid == Decimal("1.0823")
    assert q.ask == Decimal("1.0824")
    assert q.symbol == "EURUSD"


def test_get_quote_unknown_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["XYZ"] = None
    out = _call(server, "get_quote", symbol="XYZ")
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_get_quote_no_tick_available(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = None
    out = _call(server, "get_quote", symbol="EURUSD")
    assert out["error"]["code"] == "SYMBOL_NOT_ENABLED"


def test_get_symbols_no_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbols_get = (
        FakeSymbolInfo(name="EURUSD", path="Forex\\Majors\\EURUSD"),
        FakeSymbolInfo(name="XAUUSD", path="Metals\\XAUUSD"),
    )
    out = _call(server, "get_symbols")
    assert {s.name for s in out} == {"EURUSD", "XAUUSD"}
    assert {s.category for s in out} == {"Forex", "Metals"}


def test_get_symbols_with_category_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbols_get = (
        FakeSymbolInfo(name="EURUSD", path="Forex\\Majors\\EURUSD"),
        FakeSymbolInfo(name="XAUUSD", path="Metals\\XAUUSD"),
    )
    out = _call(server, "get_symbols", category="Forex")
    assert [s.name for s in out] == ["EURUSD"]


def test_get_market_hours_open_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", trade_mode=4)
    out = _call(server, "get_market_hours", symbol="EURUSD")
    assert out.symbol == "EURUSD"
    assert out.is_open is True


def test_get_market_hours_disabled_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", trade_mode=0)
    out = _call(server, "get_market_hours", symbol="EURUSD")
    assert out.is_open is False


# --- get_rates ----------------------------------------------------------


def test_get_rates_returns_bars(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._copy_rates_from_pos[("EURUSD", TIMEFRAME_H1)] = (
        FakeRate(
            time=int(datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc).timestamp()),
            open=1.0820, high=1.0830, low=1.0815, close=1.0825,
            tick_volume=100, spread=1, real_volume=0,
        ),
        FakeRate(
            time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
            open=1.0825, high=1.0840, low=1.0820, close=1.0838,
            tick_volume=120, spread=1, real_volume=0,
        ),
    )
    out = _call(server, "get_rates", symbol="EURUSD", timeframe="H1", count=10)
    assert len(out) == 2
    assert out[0].open == Decimal("1.082")
    assert out[1].close == Decimal("1.0838")


def test_get_rates_unknown_timeframe(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    out = _call(server, "get_rates", symbol="EURUSD", timeframe="INVALID", count=10)
    assert out["error"]["code"] == "INVALID_TIMEFRAME"


def test_get_rates_zero_count_rejected(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    out = _call(server, "get_rates", symbol="EURUSD", timeframe="H1", count=0)
    assert out["error"]["code"] == "INVALID_COUNT"


def test_get_rates_unknown_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["XYZ"] = None
    out = _call(server, "get_rates", symbol="XYZ", timeframe="H1", count=10)
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_get_rates_no_history(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    # No rows configured for (EURUSD, D1) → fake returns None.
    fake._copy_rates_from_pos[("EURUSD", TIMEFRAME_D1)] = None  # type: ignore[assignment]
    out = _call(server, "get_rates", symbol="EURUSD", timeframe="D1", count=10)
    assert out["error"]["code"] == "NO_RATES_AVAILABLE"


def test_get_rates_clamps_to_5000(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    # Provide 10 bars; assert the slice didn't error even though we asked for
    # 10_000_000 (the clamp prevents passing an unreasonable value to mt5lib).
    fake._copy_rates_from_pos[("EURUSD", TIMEFRAME_H1)] = tuple(
        FakeRate(time=1_745_000_000 + i * 3600) for i in range(10)
    )
    out = _call(server, "get_rates", symbol="EURUSD", timeframe="H1", count=10_000_000)
    assert len(out) == 10  # all available rows returned, no error


# --- calc_margin --------------------------------------------------------


def test_calc_margin_buy_with_explicit_price(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._order_calc_margin[("EURUSD", 0)] = 108.24  # 0.1 lot of EURUSD @ 1.0824 / 100x leverage
    out = _call(
        server, "calc_margin",
        symbol="EURUSD", side="buy",
        volume=Decimal("0.1"), price=Decimal("1.0824"),
    )
    assert out.symbol == "EURUSD"
    assert out.side == "buy"
    assert out.margin == Decimal("108.24")
    assert out.currency == "USD"


def test_calc_margin_sell_uses_bid_when_price_omitted(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(bid=1.0823, ask=1.0824)
    fake._order_calc_margin[("EURUSD", 1)] = 108.23
    out = _call(
        server, "calc_margin",
        symbol="EURUSD", side="sell", volume=Decimal("0.1"),
    )
    assert out.price == Decimal("1.0823")
    assert out.margin == Decimal("108.23")


def test_calc_margin_buy_uses_ask_when_price_omitted(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(bid=1.0823, ask=1.0824)
    fake._order_calc_margin[("EURUSD", 0)] = 108.24
    out = _call(
        server, "calc_margin",
        symbol="EURUSD", side="buy", volume=Decimal("0.1"),
    )
    assert out.price == Decimal("1.0824")


def test_calc_margin_returns_error_when_broker_refuses(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._order_calc_margin[("EURUSD", 0)] = None
    out = _call(
        server, "calc_margin",
        symbol="EURUSD", side="buy",
        volume=Decimal("0.1"), price=Decimal("1.0824"),
    )
    assert out["error"]["code"] == "MARGIN_CALC_FAILED"


def test_calc_margin_unknown_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["XYZ"] = None
    out = _call(
        server, "calc_margin",
        symbol="XYZ", side="buy",
        volume=Decimal("0.1"), price=Decimal("1.0"),
    )
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_calc_margin_no_tick_when_price_omitted(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = None
    out = _call(
        server, "calc_margin",
        symbol="EURUSD", side="buy", volume=Decimal("0.1"),
    )
    assert out["error"]["code"] == "SYMBOL_NOT_ENABLED"
