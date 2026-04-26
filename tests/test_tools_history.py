"""get_history tool."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeDeal, FakeMT5, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())  # broker +180
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_history_returns_deals(server_and_mt5):
    server, fake = server_and_mt5
    fake._history_deals_get = (
        FakeDeal(
            ticket=10, order=5, symbol="EURUSD", type=0,
            volume=0.1, price=1.0822, profit=5.0,
            time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        ),
    )
    out = _call(
        server, "get_history",
        from_ts="2026-04-20T00:00:00Z",
        to_ts="2026-04-21T23:59:59Z",
    )
    assert len(out) == 1
    assert out[0].ticket == 10
    assert out[0].type == "buy"
    assert out[0].profit == Decimal("5.0")


def test_get_history_requires_utc_timestamps(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(
        server, "get_history",
        from_ts="2026-04-20T00:00:00",  # naive — refuse
        to_ts="2026-04-21T23:59:59Z",
    )
    assert out["error"]["code"] == "INVALID_TIMESTAMP"


def test_get_history_rejects_backwards_range(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(
        server, "get_history",
        from_ts="2026-04-22T00:00:00Z",
        to_ts="2026-04-21T00:00:00Z",
    )
    assert out["error"]["code"] == "INVALID_TIMESTAMP"


def test_get_history_empty_result(server_and_mt5):
    server, fake = server_and_mt5
    fake._history_deals_get = tuple()
    out = _call(
        server, "get_history",
        from_ts="2026-04-20T00:00:00Z",
        to_ts="2026-04-21T23:59:59Z",
    )
    assert out == []


def test_get_history_shifts_range_into_broker_tz(server_and_mt5):
    """The mt5lib call must receive `datetime` objects in broker-server TZ."""
    server, fake = server_and_mt5
    from unittest.mock import patch
    with patch.object(fake, "history_deals_get", wraps=fake.history_deals_get) as spy:
        _call(
            server, "get_history",
            from_ts="2026-04-20T00:00:00Z",
            to_ts="2026-04-21T23:59:59Z",
        )
        args, kwargs = spy.call_args
        assert args[0] == datetime(2026, 4, 20, 3, 0)  # +3h in broker TZ
        assert args[1] == datetime(2026, 4, 22, 2, 59, 59)
