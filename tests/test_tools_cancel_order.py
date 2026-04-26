"""cancel_order: never gates; idempotent; INVALID_TICKET on unknown."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrder, FakeOrderSendResult, FakeSymbolInfo,
    FakeTerminalInfo, ORDER_TYPE_BUY_LIMIT, TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._orders_get = (
        FakeOrder(ticket=77, symbol="EURUSD", type=ORDER_TYPE_BUY_LIMIT,
                  price_open=1.0700, volume_initial=0.1, volume_current=0.1),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=77, volume=0.1)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\nauto_approve_notional = "0"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_cancel_pending_order_succeeds(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "cancel_order", ticket=77)
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_REMOVE
    assert sent["order"] == 77


def test_cancel_unknown_returns_invalid_ticket(server_and_mt5):
    server, fake = server_and_mt5
    fake._orders_get = ()
    out = _call(server, "cancel_order", ticket=99999)
    assert out["error"]["code"] == "INVALID_TICKET"


def test_cancel_idempotency_replay(server_and_mt5):
    server, fake = server_and_mt5
    out1 = _call(server, "cancel_order", ticket=77, idempotency_key="k1")
    assert out1["replayed"] is False
    out2 = _call(server, "cancel_order", ticket=77, idempotency_key="k1")
    assert out2["replayed"] is True
    assert len(fake.order_send_calls) == 1
