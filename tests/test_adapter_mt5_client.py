"""MT5Client lifecycle and re-init behaviour."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.errors import MT5Error
from tests.fakes import FakeMT5, FakeTerminalInfo


@pytest.fixture
def client(fake_mt5: FakeMT5, frozen_utc):
    c = MT5Client(mt5_module=fake_mt5)
    return c


def test_connect_initialises_and_caches_offset(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    # Broker says 13:00 when real UTC is 10:00 → +180 min.
    fake_mt5._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    client.connect()
    assert client.broker_offset_minutes == 180
    assert fake_mt5.calls["initialize"] == 1


def test_connect_uses_terminal_path(fake_mt5: FakeMT5, frozen_utc):
    c = MT5Client(mt5_module=fake_mt5, terminal_path="C:/mt5/terminal64.exe")
    c.connect()
    # The fake doesn't record kwargs, but we can spy via patch.
    with patch.object(fake_mt5, "initialize", wraps=fake_mt5.initialize) as spy:
        c._initialised = False
        c.connect()
    spy.assert_called_once_with("C:/mt5/terminal64.exe")


def test_connect_failure_raises(client: MT5Client, fake_mt5: FakeMT5):
    fake_mt5._initialize = False
    fake_mt5._last_error = (-10003, "IPC timeout")
    with pytest.raises(MT5Error) as ei:
        client.connect()
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_terminal_info_none_raises(client: MT5Client, fake_mt5: FakeMT5):
    fake_mt5._terminal_info = None
    with pytest.raises(MT5Error) as ei:
        client.connect()
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_shutdown_resets_state(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()
    assert client._initialised
    client.disconnect()
    assert fake_mt5.calls["shutdown"] == 1
    assert not client._initialised


def test_call_transparently_reinits_on_not_initialized(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()
    # Simulate mid-session failure: function returns None once, then recovers.
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            # mimic mt5lib: returns None and sets last_error to -10004 "not initialized"
            fake_mt5._last_error = (-10004, "not initialized")
            return None
        fake_mt5._last_error = (0, "")
        return "ok"

    result = client._call_with_reinit(flaky)
    assert result == "ok"
    assert calls["n"] == 2
    # A second `initialize` call happened during the retry.
    assert fake_mt5.calls["initialize"] == 2


def test_call_reinit_fails_hard_when_reinit_broken(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()

    def always_fails():
        fake_mt5._last_error = (-10004, "not initialized")
        return None

    # Make re-init fail too.
    fake_mt5._initialize = False
    with pytest.raises(MT5Error) as ei:
        client._call_with_reinit(always_fails)
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_ping_reports_latency(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()
    ok, ms = client.ping()
    assert ok is True
    assert ms >= 0


def test_ping_false_when_disconnected(fake_mt5: FakeMT5, frozen_utc):
    c = MT5Client(mt5_module=fake_mt5)
    fake_mt5._terminal_info = None
    ok, _ = c.ping()
    assert ok is False


def test_connect_falls_back_when_terminal_info_lacks_time(fake_mt5: FakeMT5, frozen_utc, caplog):
    """Some MT5 builds omit .time from TerminalInfo. Adapter falls back to offset=0."""
    from dataclasses import dataclass

    @dataclass
    class _BrokenTerminalInfo:
        connected: bool = True
        trade_allowed: bool = True
        build: int = 4150
        name: str = "MetaTrader 5"
        company: str = "Broker Ltd"
        path: str = ""
        # no `time` field — this is what some real MT5 builds omit

    fake_mt5._terminal_info = _BrokenTerminalInfo()
    client = MT5Client(mt5_module=fake_mt5)

    import logging
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.adapter.mt5_client"):
        client.connect()

    assert client._initialised is True
    assert client.broker_offset_minutes == 0
    assert any("terminal_info().time not available" in r.message for r in caplog.records)
