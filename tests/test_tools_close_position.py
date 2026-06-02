"""close_position end-to-end."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrderSendResult, FakePosition, FakeSymbolInfo,
    FakeTerminalInfo, FakeTick, POSITION_TYPE_BUY, POSITION_TYPE_SELL,
    TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.0823, ask=1.0824)}
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=0.5, price_open=1.0800, price_current=1.0824,
                     profit=12.0),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=42, deal=999,
                                            volume=0.5, price=1.0823)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\n'
        'auto_approve_notional = "1000000"\n'  # don't gate small closes
        'max_realised_loss_per_close = "100"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_close_in_full(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "close_position", ticket=42)
    assert out["success"] is True
    assert out["ticket"] == 42
    assert len(fake.order_send_calls) == 1
    sent = fake.order_send_calls[0]
    assert sent["volume"] == 0.5
    # A buy position is closed by sending a SELL deal.
    assert sent["type"] == fake.ORDER_TYPE_SELL
    assert sent["position"] == 42  # mt5lib uses `position` for close-by-ticket


def test_close_partial_volume(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "close_position", ticket=42, volume="0.2")
    assert out["success"] is True
    assert fake.order_send_calls[0]["volume"] == 0.2


def test_close_unknown_ticket_returns_invalid_ticket(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = ()
    out = _call(server, "close_position", ticket=99999)
    assert "error" in out
    assert out["error"]["code"] == "INVALID_TICKET"


def test_close_blocked_by_max_realised_loss_per_close(tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.05, ask=1.0501)}
    # Buy at 1.10, current 1.05 → realising a loss of (1.10-1.05)*1.0 = 0.05 on volume=1.0.
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=1.0, price_open=1.10, price_current=1.05,
                     profit=-5000.0),
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\n'
        'max_realised_loss_per_close = "0.01"\n'
        f'\n[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = server._tool_manager.get_tool("close_position").fn(ticket=42)
    assert "error" in out
    assert out["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"
    assert out["error"]["details"]["limit_name"] == "max_realised_loss_per_close"


def test_default_config_is_fail_closed_for_close(tmp_path, frozen_utc):
    """Fail-closed default: with no auto_approve_notional configured (default 0),
    even a small close requires human approval instead of auto-executing."""
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.0823, ask=1.0824)}
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=0.5, price_open=1.0800, price_current=1.0824,
                     profit=12.0),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=42, deal=999,
                                            volume=0.5, price=1.0823)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        # No [policy] block → auto_approve_notional defaults to 0 (fail-closed).
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = server._tool_manager.get_tool("close_position").fn(ticket=42)
    # Did NOT execute; returned an approval preview instead.
    assert len(fake.order_send_calls) == 0
    assert out.get("action") == "close_position"
    assert "request_id" in out


def test_close_sell_position_uses_ask_and_buy_order(server_and_mt5):
    """Sell positions close at ASK with a BUY order (mirror of the buy-close path).

    Regression guard: a swap of bid/ask or a wrong order-type branch would
    silently produce a wrong-direction close. This test pins both."""
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=43, symbol="EURUSD", type=fake.POSITION_TYPE_SELL,
                     volume=0.3, price_open=1.0850, price_current=1.0824,
                     profit=8.0),
    )
    out = _call(server, "close_position", ticket=43)
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["type"] == fake.ORDER_TYPE_BUY      # sell position closed by BUY
    assert sent["price"] == 1.0824                  # closing at ASK


def test_close_falls_back_to_price_current_when_tick_missing(server_and_mt5):
    """When symbol_info_tick returns None mid-session (broker maintenance,
    news blackout), close_position falls back to the position's
    `price_current` so the agent can still exit. The caller retains full
    audit trail; the close just uses the last known broker price.
    """
    server, fake = server_and_mt5
    fake._symbol_info_tick = {"EURUSD": None}
    out = _call(server, "close_position", ticket=42)
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    # Buy position close → SELL deal at price_current (1.0824 from fixture).
    assert sent["type"] == fake.ORDER_TYPE_SELL
    assert sent["price"] == 1.0824


def test_close_errors_when_tick_missing_and_price_current_zero(server_and_mt5):
    """If both tick AND position price_current are unavailable, surface
    SYMBOL_NOT_ENABLED — there's nothing to fall back to."""
    server, fake = server_and_mt5
    fake._symbol_info_tick = {"EURUSD": None}
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=0.5, price_open=1.0800, price_current=0.0),
    )
    out = _call(server, "close_position", ticket=42)
    assert "error" in out
    assert out["error"]["code"] == "SYMBOL_NOT_ENABLED"
    assert len(fake.order_send_calls) == 0


def test_close_errors_when_tick_missing_and_close_above_approval_threshold(tmp_path, frozen_utc):
    """The tick fallback only applies to closes that auto-approve. If the
    close needs human approval, the human needs a fresh quote — refuse
    rather than synthesise a stale preview."""
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": None}
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=10.0, price_open=1.0800, price_current=1.0824),
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\nauto_approve_notional = "1"\n\n'  # gate everything
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = server._tool_manager.get_tool("close_position").fn(ticket=42)
    assert "error" in out
    assert out["error"]["code"] == "SYMBOL_NOT_ENABLED"
    assert len(fake.order_send_calls) == 0


def test_close_unsupported_position_type_returns_explicit_error(server_and_mt5):
    """A position with an unrecognised type (neither BUY nor SELL) must
    surface UNSUPPORTED_POSITION_TYPE — not silently default to one side."""
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=44, symbol="EURUSD", type=99,  # bogus type
                     volume=0.5, price_open=1.0800, price_current=1.0824,
                     profit=12.0),
    )
    out = _call(server, "close_position", ticket=44)
    assert "error" in out
    assert out["error"]["code"] == "UNSUPPORTED_POSITION_TYPE"
    assert out["error"]["details"]["ticket"] == 44
    assert out["error"]["details"]["position_type"] == 99
    # Critically, no order was sent — the guard fires before order_send.
    assert len(fake.order_send_calls) == 0
