"""End-to-end coverage for place_order — the canonical Phase-2 tool flow."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrderSendResult, FakeSymbolInfo, FakeTerminalInfo,
    FakeTick, TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo(currency="USD", leverage=100)
    info = FakeSymbolInfo(name="EURUSD", visible=True, volume_max=100_000.0)
    fake._symbol_info = {"EURUSD": info}
    fake._symbol_info_tick = {
        "EURUSD": FakeTick(time=int(datetime(2026, 4, 21, 13, 0,
                                              tzinfo=timezone.utc).timestamp()),
                           bid=1.0823, ask=1.0824)
    }
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=12345, deal=99,
                                            volume=0.10, price=1.0824)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\n'
        'auto_approve_notional = "1000"\n'
        'max_notional_per_trade = "100000"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_small_notional_executes_directly(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="0.10")
    assert out["success"] is True
    assert out["ticket"] == 12345
    assert out["replayed"] is False
    assert len(fake.order_send_calls) == 1
    sent = fake.order_send_calls[0]
    assert sent["symbol"] == "EURUSD"
    assert sent["volume"] == 0.10
    assert sent["type"] == fake.ORDER_TYPE_BUY
    assert sent["price"] == 1.0824


def test_above_threshold_returns_preview(server_and_mt5):
    server, fake = server_and_mt5
    # 10.0 lots × 1.0824 = 10.824 notional > 1000 threshold (oh wait, it's not).
    # Actually with auto_approve_notional="1000" and notional=10.824, this is BELOW.
    # The threshold is interpreted in raw "volume × price" terms — for FX it's tiny.
    # Use a much larger volume to trigger.
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="10000.0")
    assert len(fake.order_send_calls) == 0
    assert out["action"] == "place_order"
    assert "request_id" in out
    assert "expires_at" in out
    assert "summary" in out


def test_approval_confirmed_retry_executes(server_and_mt5):
    server, fake = server_and_mt5
    preview = _call(server, "place_order",
                    symbol="EURUSD", side="buy", type="market", volume="10000.0")
    request_id = preview["request_id"]
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="10000.0",
                approval_confirmed=True, approval_request_id=request_id)
    assert out["success"] is True
    assert out["ticket"] == 12345


def test_above_max_notional_rejected_even_with_approval(tmp_path):
    """Pre-flight refusals are absolute — approval doesn't override."""
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.0823, ask=1.0824)}
    cfg = tmp_path / "config2.toml"
    cfg.write_text(
        '[policy]\n'
        'auto_approve_notional = "0"\n'
        'max_notional_per_trade = "5"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = server._tool_manager.get_tool("place_order").fn(
        symbol="EURUSD", side="buy", type="market", volume="10.0",
        approval_confirmed=True, approval_request_id="01HX...",
    )
    assert "error" in out
    assert out["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"
    assert out["error"]["details"]["limit_name"] == "max_notional_per_trade"
    assert len(fake.order_send_calls) == 0


def test_idempotency_replay_returns_cached_with_replayed_true(server_and_mt5):
    server, fake = server_and_mt5
    out1 = _call(server, "place_order",
                 symbol="EURUSD", side="buy", type="market", volume="0.10",
                 idempotency_key="k-once")
    assert out1["success"] is True and out1["replayed"] is False
    out2 = _call(server, "place_order",
                 symbol="EURUSD", side="buy", type="market", volume="0.10",
                 idempotency_key="k-once")
    assert out2["replayed"] is True
    assert out2["ticket"] == 12345
    assert len(fake.order_send_calls) == 1


def test_invalid_symbol_returns_symbol_not_found(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "place_order",
                symbol="UNKNOWN", side="buy", type="market", volume="0.10")
    assert "error" in out
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_unparseable_sl_returns_invalid_request(server_and_mt5):
    """Companion to modify_order's regression test: a malformed SL string
    must surface as INVALID_REQUEST with the offending field, not be
    swallowed into INTERNAL_ERROR via decimal.InvalidOperation."""
    server, fake = server_and_mt5
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="0.10",
                sl="not-a-number")
    assert out["error"]["code"] == "INVALID_REQUEST"
    assert out["error"]["details"]["field"] == "sl"
    assert out["error"]["details"]["value"] == "not-a-number"
    assert len(fake.order_send_calls) == 0


def test_unparseable_volume_returns_invalid_request(server_and_mt5):
    """Required-field variant: bad volume string also surfaces as
    INVALID_REQUEST, not INTERNAL_ERROR."""
    server, fake = server_and_mt5
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="0,10")
    assert out["error"]["code"] == "INVALID_REQUEST"
    assert out["error"]["details"]["field"] == "volume"
    assert len(fake.order_send_calls) == 0
