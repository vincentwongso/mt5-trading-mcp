from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeMT5, FakePosition, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_positions_no_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=1, symbol="EURUSD"),
        FakePosition(ticket=2, symbol="GBPUSD"),
    )
    out = _call(server, "get_positions")
    assert [p.ticket for p in out] == [1, 2]


def test_get_positions_symbol_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=1, symbol="EURUSD"),
        FakePosition(ticket=2, symbol="GBPUSD"),
    )
    out = _call(server, "get_positions", symbol="EURUSD")
    assert [p.ticket for p in out] == [1]


def test_get_positions_empty(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(server, "get_positions")
    assert out == []
