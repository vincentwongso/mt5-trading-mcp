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
    """Some MT5 builds omit .time from TerminalInfo AND the broker isn't streaming.

    When neither source can be sampled, the adapter falls back to offset=0
    rather than refusing to start; the warning explains the consequence.
    """
    from dataclasses import dataclass

    @dataclass
    class _BrokenTerminalInfo:
        connected: bool = True
        trade_allowed: bool = True
        build: int = 4150
        name: str = "MetaTrader 5"
        company: str = "FintrixMarkets Ltd"
        path: str = ""
        # no `time` field — this is what some real MT5 builds omit

    fake_mt5._terminal_info = _BrokenTerminalInfo()
    # No `_symbol_info_tick` entries → every probe call returns None.
    client = MT5Client(mt5_module=fake_mt5)

    import logging
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.adapter.mt5_client"):
        client.connect()

    assert client._initialised is True
    assert client.broker_offset_minutes == 0
    assert any(
        "Could not derive broker TZ offset" in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]


def test_connect_derives_offset_from_tick_when_terminal_info_lacks_time(
    fake_mt5: FakeMT5, frozen_utc, caplog,
):
    """When .time is absent, fall back to the freshest probe-symbol tick.

    BTCUSD streams 24/7 on most retail brokers, so it's the canonical
    probe. A fresh BTCUSD tick at broker-local 13:00 paired with real
    UTC 10:00 (the frozen clock) implies broker offset = +180 min.
    """
    from dataclasses import dataclass

    from tests.fakes import FakeTick

    @dataclass
    class _BrokenTerminalInfo:
        connected: bool = True
        trade_allowed: bool = True
        build: int = 4150
        name: str = "MetaTrader 5"
        company: str = "FintrixMarkets Ltd"
        path: str = ""

    fake_mt5._terminal_info = _BrokenTerminalInfo()
    # Broker says 13:00 (broker-local-treated-as-UTC) when real UTC
    # is 10:00 → +180 min. The frozen_utc fixture pins real now
    # to 2026-04-21T10:00:00Z.
    fake_mt5._symbol_info_tick["BTCUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    client = MT5Client(mt5_module=fake_mt5)

    import logging
    with caplog.at_level(logging.INFO, logger="mt5_mcp.adapter.mt5_client"):
        client.connect()

    assert client._initialised is True
    assert client.broker_offset_minutes == 180
    assert any(
        "Derived broker TZ offset" in r.message and "BTCUSD" in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]


def test_connect_rejects_stale_tick_for_offset_inference(
    fake_mt5: FakeMT5, frozen_utc, caplog,
):
    """A weekend-stale tick must not pollute the offset.

    Tick time records broker-time-then; comparing to real-utc-now would
    add the staleness to the apparent offset. The adapter validates the
    candidate offset by re-applying it and checking the tick's residual
    age; a >5-minute residual is rejected and the next probe is tried.
    """
    from dataclasses import dataclass

    from tests.fakes import FakeTick

    @dataclass
    class _BrokenTerminalInfo:
        connected: bool = True
        trade_allowed: bool = True
        build: int = 4150
        name: str = "MetaTrader 5"
        company: str = "FintrixMarkets Ltd"
        path: str = ""

    fake_mt5._terminal_info = _BrokenTerminalInfo()
    # Tick from 2 days ago at broker-local 13:00. The naive offset
    # inference would yield -2820 min (≈ -47h). The validation step
    # rejects this, and with no other probe tick set, we fall through
    # to offset=0 with a warning.
    fake_mt5._symbol_info_tick["BTCUSD"] = FakeTick(
        time=int(datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    client = MT5Client(mt5_module=fake_mt5)

    import logging
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.adapter.mt5_client"):
        client.connect()

    assert client._initialised is True
    assert client.broker_offset_minutes == 0
    assert any(
        "Could not derive broker TZ offset" in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]
