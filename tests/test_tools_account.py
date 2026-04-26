"""get_account_info tool."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeAccountInfo, FakeMT5, FakeTerminalInfo


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


def test_get_account_info_populates(server_and_mt5):
    server, fake = server_and_mt5
    fake._account_info = FakeAccountInfo(
        login=42, name="Vincent", server="FX-Demo", currency="USD",
        balance=5_000.0, equity=5_010.0, margin=50.0, margin_free=4_960.0,
        margin_level=10020.0, leverage=100, trade_allowed=True, margin_mode=0,
    )
    info = _call(server, "get_account_info")
    assert info.login == 42
    assert info.currency == "USD"
    assert info.balance == Decimal("5000.0")
    assert info.margin_mode == "retail_netting"


def test_get_account_info_errors_when_none(server_and_mt5):
    server, fake = server_and_mt5
    fake._account_info = None
    out = _call(server, "get_account_info")
    assert out["error"]["code"] == "TERMINAL_NOT_CONNECTED"
