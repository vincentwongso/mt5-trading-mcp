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
    ok, ms, via = client.ping()
    assert ok is True
    assert ms >= 0
    assert via == "terminal_info"


def test_ping_falls_back_to_account_info_when_terminal_info_none(
    client: MT5Client, fake_mt5: FakeMT5, frozen_utc,
):
    """Regression for the v1.0.8 false-negative: some MT5 builds return
    None from terminal_info() even when the terminal is fully connected.
    ping must consult account_info before reporting unhealthy."""
    client.connect()
    fake_mt5._terminal_info = None
    ok, _, via = client.ping()
    assert ok is True
    assert via == "account_info"


def test_ping_falls_back_to_tick_probe_when_terminal_and_account_unavailable(
    fake_mt5: FakeMT5, frozen_utc,
):
    """When both terminal_info() and account_info() return None but the
    broker is still streaming quotes, ping should treat that as healthy.

    Uses a fresh MT5Client without calling connect() so broker_offset_minutes
    stays at 0 (default); the tick freshness check then compares broker-epoch
    directly against frozen real-UTC."""
    from datetime import datetime, timezone
    from tests.fakes import FakeTick
    c = MT5Client(mt5_module=fake_mt5)
    fake_mt5._terminal_info = None
    fake_mt5._account_info = None
    fresh_epoch = int(datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc).timestamp())
    fake_mt5._symbol_info_tick = {
        "BTCUSD": FakeTick(time=fresh_epoch, bid=50000.0, ask=50001.0),
    }
    ok, _, via = c.ping()
    assert ok is True
    assert via == "tick_probe"


def test_ping_recovers_from_not_initialized_via_call_wrapper(
    client: MT5Client, fake_mt5: FakeMT5, frozen_utc,
):
    """Regression for the v1.0.10 false-negative left over from routing
    layers through direct mt5lib calls: when the IPC is in NOT_INITIALIZED
    state, direct calls return None and ping would report ok=false even
    though every other read tool transparently reinits and succeeds.
    Routing each ping layer through self.call() lets ping see the same
    healed state."""
    client.connect()
    initial_inits = fake_mt5.calls["initialize"]
    # Arm the first terminal_info() call to look like a NOT_INITIALIZED
    # session, then recover on retry (mt5lib re-initializes inside call()).
    real_terminal_info = fake_mt5.terminal_info
    state = {"first": True}

    def flaky_terminal_info():
        if state["first"]:
            state["first"] = False
            fake_mt5._last_error = (-10004, "not initialized")
            return None
        fake_mt5._last_error = (0, "")
        return real_terminal_info()

    fake_mt5.terminal_info = flaky_terminal_info  # type: ignore[method-assign]
    ok, _, via = client.ping()
    assert ok is True
    assert via == "terminal_info"
    # The reinit wrapper called initialize() a second time during the retry.
    assert fake_mt5.calls["initialize"] == initial_inits + 1


def test_ping_rejects_stale_tick(fake_mt5: FakeMT5, frozen_utc):
    """A tick older than _FRESH_TICK_SECONDS (5min) is not a healthy signal —
    the terminal could be connected to a frozen quote stream."""
    from datetime import datetime, timezone
    from tests.fakes import FakeTick
    c = MT5Client(mt5_module=fake_mt5)
    fake_mt5._terminal_info = None
    fake_mt5._account_info = None
    stale_epoch = int(datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc).timestamp())  # 1h before frozen now
    fake_mt5._symbol_info_tick = {
        "BTCUSD": FakeTick(time=stale_epoch, bid=50000.0, ask=50001.0),
    }
    ok, _, via = c.ping()
    assert ok is False
    assert via is None


def test_ping_false_when_all_layers_fail(fake_mt5: FakeMT5, frozen_utc):
    """Genuinely disconnected terminal: no layer can answer."""
    c = MT5Client(mt5_module=fake_mt5)
    fake_mt5._terminal_info = None
    fake_mt5._account_info = None
    fake_mt5._symbol_info_tick = {}
    ok, _, via = c.ping()
    assert ok is False
    assert via is None


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
        company: str = "Example Broker Ltd"
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
        company: str = "Example Broker Ltd"
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
        company: str = "Example Broker Ltd"
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


# ---------------------------------------------------------------------------
# Task 2: lazy backend resolution + resolve_mt5_module
# ---------------------------------------------------------------------------

def test_native_backend_import_is_lazy_not_at_construction():
    """Constructing MT5Client must NOT resolve the backend; only first use does.
    This is what lets `serve`/`doctor` start on a box without MetaTrader5."""
    from mt5_mcp.adapter.mt5_client import MT5Client
    calls = []

    def factory():
        calls.append(True)
        raise RuntimeError("resolved too early")

    client = MT5Client(mt5_factory=factory)
    assert calls == []                      # not resolved at construction
    import pytest
    with pytest.raises(RuntimeError):
        _ = client.mt5                      # first access resolves it
    assert calls == [True]


def test_injected_module_never_calls_factory(fake_mt5):
    from mt5_mcp.adapter.mt5_client import MT5Client

    def factory():
        raise AssertionError("factory must not run when a module is injected")

    client = MT5Client(mt5_module=fake_mt5, mt5_factory=factory)
    assert client.mt5 is fake_mt5


def test_resolve_native_when_no_bridge(monkeypatch):
    from mt5_mcp.adapter import mt5_client as mod
    from mt5_mcp.config import Config
    sentinel = object()
    monkeypatch.setattr(mod, "_import_mt5", lambda: sentinel)
    assert mod.resolve_mt5_module(Config()) is sentinel


def test_resolve_bridge_constructs_client_with_host_port(monkeypatch):
    import sys, types
    from mt5_mcp.adapter import mt5_client as mod
    from mt5_mcp.config import Config

    captured = {}

    class FakeRPyC:
        def __init__(self, host, port):
            captured["host"] = host
            captured["port"] = port

    fake_mod = types.ModuleType("mt5linux")
    fake_mod.MetaTrader5 = FakeRPyC
    monkeypatch.setitem(sys.modules, "mt5linux", fake_mod)

    cfg = Config(mt5={"bridge": {"host": "10.0.0.5", "port": 9001}})
    proxy = mod.resolve_mt5_module(cfg)
    assert isinstance(proxy, FakeRPyC)
    assert captured == {"host": "10.0.0.5", "port": 9001}


def test_resolve_bridge_missing_client_lib_raises_terminal_not_connected(monkeypatch):
    import sys
    from mt5_mcp.adapter import mt5_client as mod
    from mt5_mcp.config import Config
    from mt5_mcp.errors import MT5Error

    # Ensure the import fails.
    monkeypatch.setitem(sys.modules, "mt5linux", None)  # forces ImportError
    cfg = Config(mt5={"bridge": {"host": "127.0.0.1", "port": 8001}})
    import pytest
    with pytest.raises(MT5Error) as ei:
        mod.resolve_mt5_module(cfg)
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_resolve_native_missing_lib_raises_terminal_not_connected(monkeypatch):
    from mt5_mcp.adapter import mt5_client as mod
    from mt5_mcp.config import Config
    from mt5_mcp.errors import MT5Error

    def boom():
        raise ImportError("No module named 'MetaTrader5'")

    monkeypatch.setattr(mod, "_import_mt5", boom)
    import pytest
    with pytest.raises(MT5Error) as ei:
        mod.resolve_mt5_module(Config())
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"
