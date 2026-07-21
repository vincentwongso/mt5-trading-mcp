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
    # No rows configured for (EURUSD, D1) -> fake returns None.
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


# --- get_chart_screenshot ------------------------------------------------


def test_get_chart_screenshot_not_supported_off_windows(server_and_mt5, monkeypatch):
    server, _fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Linux")
    out = _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1")
    assert out["error"]["code"] == "SCREENSHOT_NOT_SUPPORTED"


def test_get_chart_screenshot_bad_timeframe(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    out = _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="Z9")
    assert out["error"]["code"] == "INVALID_TIMEFRAME"


def test_get_chart_screenshot_returns_image(server_and_mt5, monkeypatch):
    from mcp.server.fastmcp import Image

    server, fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    monkeypatch.setattr(market, "capture_chart", lambda *a, **k: b"PNGDATA")
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")

    out = _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1")
    assert isinstance(out, Image)
    assert out.data == b"PNGDATA"


def test_get_chart_screenshot_unknown_symbol(server_and_mt5, monkeypatch):
    server, _fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    # No FakeSymbolInfo registered -> ctx.symbols.get raises SYMBOL_NOT_FOUND.
    out = _call(server, "get_chart_screenshot", symbol="NOPE", timeframe="H1")
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_get_chart_screenshot_not_supported_precedes_connection(server_and_mt5, monkeypatch):
    from mt5_mcp.types import ErrorDetail
    import mt5_mcp.tools.market as market
    import mt5_mcp.tools._common as common

    server, _fake = server_and_mt5
    monkeypatch.setattr(market.platform, "system", lambda: "Linux")
    # Simulate a host with no reachable terminal: if the platform guard did not
    # run before the connection, error_envelope's ensure_connected would win and
    # the tool would return TERMINAL_NOT_CONNECTED instead of the correct code.
    monkeypatch.setattr(
        common,
        "ensure_connected",
        lambda ctx: ErrorDetail(
            code="TERMINAL_NOT_CONNECTED",
            message="no terminal",
            retryable=True,
            requires_human=False,
        ),
    )
    out = _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1")
    assert out["error"]["code"] == "SCREENSHOT_NOT_SUPPORTED"


def test_get_chart_screenshot_invalid_annotation_precedes_connection(server_and_mt5, monkeypatch):
    """Annotation validation must also run before error_envelope's connect.

    Mirrors test_get_chart_screenshot_not_supported_precedes_connection: on a
    host with no reachable terminal, an invalid annotation must still surface
    INVALID_ANNOTATION rather than being masked by TERMINAL_NOT_CONNECTED.
    """
    from mt5_mcp.types import ErrorDetail
    import mt5_mcp.tools.market as market
    import mt5_mcp.tools._common as common

    server, _fake = server_and_mt5
    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        common,
        "ensure_connected",
        lambda ctx: ErrorDetail(
            code="TERMINAL_NOT_CONNECTED",
            message="no terminal",
            retryable=True,
            requires_human=False,
        ),
    )
    out = _call(
        server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1",
        annotations=[{"type": "hline", "price": "1", "role": "nope"}],
    )
    assert out["error"]["code"] == "INVALID_ANNOTATION"


def test_get_chart_screenshot_rejects_bad_annotation(server_and_mt5, monkeypatch):
    """Invalid annotations fail the whole call, before the bridge is touched."""
    server, fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    called = []
    monkeypatch.setattr(
        market, "capture_chart", lambda *a, **k: called.append(k) or b"PNG"
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")

    out = _call(
        server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1",
        annotations=[{"type": "hline", "price": "1", "role": "nope"}],
    )
    assert out["error"]["code"] == "INVALID_ANNOTATION"
    assert called == []          # bridge never reached


def test_get_chart_screenshot_passes_serialized_lines(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    seen = {}
    monkeypatch.setattr(
        market, "capture_chart", lambda *a, **k: seen.update(k) or b"PNGDATA"
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")

    _call(
        server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1",
        annotations=[{"type": "hline", "price": "2650", "role": "resistance"}],
    )
    assert seen["annotation_lines"] == ["A|hline|2650|2237106|0|"]


def test_get_chart_screenshot_without_annotations_passes_empty(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    import mt5_mcp.tools.market as market

    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    seen = {}
    monkeypatch.setattr(
        market, "capture_chart", lambda *a, **k: seen.update(k) or b"PNGDATA"
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")

    _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1")
    assert seen["annotation_lines"] == []


def test_get_chart_screenshot_scale_and_bars_rejected(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    from mt5_mcp.tools import market
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    out = _call(server, "get_chart_screenshot", symbol="EURUSD",
                timeframe="H1", scale=2, bars=100)
    assert out["error"]["code"] == "INVALID_VIEWPORT"


def test_get_chart_screenshot_invalid_viewport_precedes_connection(server_and_mt5, monkeypatch):
    """Mirror the annotation precedence test: a bad viewport must surface
    INVALID_VIEWPORT, not TERMINAL_NOT_CONNECTED, on a host with no terminal."""
    server, fake = server_and_mt5
    from mt5_mcp.tools import market
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    # Force ensure_connected to blow up if it is ever reached before validation.
    monkeypatch.setattr(
        market, "capture_chart",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("connected too early")),
    )
    out = _call(server, "get_chart_screenshot", symbol="EURUSD",
                timeframe="H1", scale=99)
    assert out["error"]["code"] == "INVALID_VIEWPORT"


def test_get_chart_screenshot_bad_end_time_is_invalid_timestamp(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    from mt5_mcp.tools import market
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    out = _call(server, "get_chart_screenshot", symbol="EURUSD",
                timeframe="H1", end_time="nope")
    assert out["error"]["code"] == "INVALID_TIMESTAMP"


def test_get_chart_screenshot_passes_viewport_fields(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    from mt5_mcp.tools import market
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    seen: dict = {}
    monkeypatch.setattr(
        market, "capture_chart", lambda *a, **k: seen.update(k) or b"PNGDATA"
    )
    _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1",
          scale=3, price_min=2600.0, price_max=2700.0)
    assert seen["viewport_fields"] == ["3", "", "", "2600", "2700"]


def test_get_chart_screenshot_no_viewport_passes_empty(server_and_mt5, monkeypatch):
    server, fake = server_and_mt5
    from mt5_mcp.tools import market
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    monkeypatch.setattr(market.platform, "system", lambda: "Windows")
    seen: dict = {}
    monkeypatch.setattr(
        market, "capture_chart", lambda *a, **k: seen.update(k) or b"PNGDATA"
    )
    _call(server, "get_chart_screenshot", symbol="EURUSD", timeframe="H1")
    assert seen["viewport_fields"] == []
