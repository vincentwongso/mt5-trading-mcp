"""Market tools: get_quote, get_symbols, get_market_hours."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


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
