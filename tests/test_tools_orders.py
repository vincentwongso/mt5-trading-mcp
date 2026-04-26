from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeMT5, FakeOrder, FakeTerminalInfo


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


def test_get_orders_returns_all(server_and_mt5):
    server, fake = server_and_mt5
    fake._orders_get = (
        FakeOrder(ticket=10, symbol="EURUSD", type=2),
        FakeOrder(ticket=11, symbol="GBPUSD", type=3),
    )
    out = _call(server, "get_orders")
    assert [o.ticket for o in out] == [10, 11]
    assert [o.type for o in out] == ["buy_limit", "sell_limit"]


def test_get_orders_symbol_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._orders_get = (
        FakeOrder(ticket=10, symbol="EURUSD", type=2),
        FakeOrder(ticket=11, symbol="GBPUSD", type=3),
    )
    out = _call(server, "get_orders", symbol="EURUSD")
    assert [o.ticket for o in out] == [10]


def test_get_orders_empty(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(server, "get_orders")
    assert out == []
