"""modify_order: covers pending-order edits AND position SL/TP changes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrder, FakeOrderSendResult, FakePosition,
    FakeSymbolInfo, FakeTerminalInfo, FakeTick, ORDER_TYPE_BUY_LIMIT,
    POSITION_TYPE_BUY, POSITION_TYPE_SELL, TRADE_RETCODE_DONE,
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
                     sl=1.0750, tp=1.0900),
    )
    fake._orders_get = (
        FakeOrder(ticket=77, symbol="EURUSD", type=ORDER_TYPE_BUY_LIMIT,
                  price_open=1.0700, volume_initial=0.1, volume_current=0.1),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=42, deal=0,
                                            volume=0.5, price=1.0824)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\nauto_approve_notional = "1000000"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_tighten_sl_on_position_auto_approves(server_and_mt5):
    """Moving SL closer to current price (more protective) auto-approves."""
    server, fake = server_and_mt5
    # Position: buy @ 1.08, current 1.0823, old SL 1.0750. New SL 1.0790 is tighter.
    out = _call(server, "modify_order", ticket=42, sl="1.0790")
    assert out["success"] is True
    assert len(fake.order_send_calls) == 1
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_SLTP
    assert sent["sl"] == 1.0790


def test_widen_sl_on_position_requires_approval(server_and_mt5):
    """Moving SL further from current price (less protective) trips the gate."""
    server, fake = server_and_mt5
    # Old SL 1.0750. New SL 1.0700 is further from current (1.0823) -> widening.
    out = _call(server, "modify_order", ticket=42, sl="1.0700")
    assert "request_id" in out
    assert out["action"] == "modify_order"
    assert len(fake.order_send_calls) == 0


def test_remove_sl_requires_approval(server_and_mt5):
    """Setting SL to 0 when previously set is the most permissive change."""
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=42, sl="0")
    assert "request_id" in out


def test_widen_sl_auto_executes_when_gate_off(frozen_utc, tmp_path: Path):
    """With the consent gate off (default auto_approve_notional=0, full-open),
    even widening a stop auto-executes - no approval preview. The widening gate
    only arms when auto_approve_notional > 0."""
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
                     sl=1.0750, tp=1.0900),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=42, deal=0, volume=0.5, price=1.0824)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        # No [policy] block → auto_approve_notional defaults to 0 (gate off).
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = _call(server, "modify_order", ticket=42, sl="1.0700")  # widening
    assert "request_id" not in out
    assert out["success"] is True
    assert len(fake.order_send_calls) == 1


def test_modify_pending_order_price(server_and_mt5):
    """Edit the limit price of a pending buy_limit order."""
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=77, price="1.0680")
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_MODIFY
    assert sent["order"] == 77
    assert sent["price"] == 1.0680


def test_modify_unknown_ticket(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=99999, sl="1.07")
    assert out["error"]["code"] == "INVALID_TICKET"


def test_modify_pending_order_with_expiration_uses_specified_time(server_and_mt5):
    """Passing an expiration switches type_time to ORDER_TIME_SPECIFIED and
    includes type_expiration as a Unix timestamp.

    Regression guard: a previous version of modify_order parsed `expiration`
    into the request model but silently dropped it from the mt5 dict.
    """
    from datetime import datetime, timezone
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=77,
                price="1.0680",
                expiration="2026-05-01T00:00:00Z")
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["type_time"] == fake.ORDER_TIME_SPECIFIED
    expected_epoch = int(datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    assert sent["type_expiration"] == expected_epoch


def test_widen_tp_on_sell_position_requires_approval(server_and_mt5):
    """SELL position: entered short at 1.0850, TP currently 1.0700 (below
    current 1.0823, taking profit on a drop). Moving TP to 1.0500 widens
    the distance from current price → trips the approval gate.

    Companion to test_widen_sl_on_position_requires_approval, which only
    covered BUY+SL. This pins both the SELL leg and the TP axis."""
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=43, symbol="EURUSD", type=POSITION_TYPE_SELL,
                     volume=0.5, price_open=1.0850, price_current=1.0823,
                     sl=1.0900, tp=1.0700),
    )
    out = _call(server, "modify_order", ticket=43, tp="1.0500")
    assert "request_id" in out
    assert out["action"] == "modify_order"
    assert len(fake.order_send_calls) == 0


def test_widen_tp_on_sell_position_round_trips_through_mt5_dict(server_and_mt5):
    """After human approval, the new TP makes it to the broker request dict
    (not silently dropped). Regression guard for the same class of bug
    that hit `expiration` parsing."""
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=43, symbol="EURUSD", type=POSITION_TYPE_SELL,
                     volume=0.5, price_open=1.0850, price_current=1.0823,
                     sl=1.0900, tp=1.0700),
    )
    # First call: gate triggers, returns preview with request_id.
    preview = _call(server, "modify_order", ticket=43, tp="1.0500")
    request_id = preview["request_id"]

    # Retry with approval_confirmed and the same fields.
    out = _call(server, "modify_order", ticket=43, tp="1.0500",
                approval_confirmed=True, approval_request_id=request_id)
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_SLTP
    assert sent["position"] == 43
    assert sent["tp"] == 1.0500
    # SL was not requested → preserved from the original position.
    assert sent["sl"] == 1.0900


def test_modify_unparseable_sl_returns_invalid_request(server_and_mt5):
    """Regression: a malformed SL string used to escape as INTERNAL_ERROR
    via `decimal.InvalidOperation`, losing which field broke. A caller's
    'SL-modify failed → close the position' branch could then unwind a clean
    fill. Now surfaces as INVALID_REQUEST with the offending field+value so
    callers can correct the next call."""
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=42, sl="not-a-number")
    assert out["error"]["code"] == "INVALID_REQUEST"
    assert out["error"]["details"]["field"] == "sl"
    assert out["error"]["details"]["value"] == "not-a-number"
    # Must NOT have reached the broker.
    assert len(fake.order_send_calls) == 0


def test_modify_pending_order_without_expiration_uses_gtc(server_and_mt5):
    """When expiration is omitted, type_time defaults to ORDER_TIME_GTC (=0
    in the real mt5lib)."""
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=77, price="1.0680")
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["type_time"] == fake.ORDER_TIME_GTC
    assert "type_expiration" not in sent
