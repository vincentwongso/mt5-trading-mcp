from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.config import StreamingSection
from mt5_mcp.streaming.dispatcher import Dispatcher
from mt5_mcp.streaming.poller import Poller
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)
from tests.fakes import FakeAccountInfo, FakeMT5, FakePosition, FakeTick


@dataclass
class RecordingDispatcher:
    """Records dispatch_* calls for poller-level tests, exposes a fixed symbol set."""
    symbols: set[str] = field(default_factory=set)
    ticks: list[tuple[str, TickSnapshot]] = field(default_factory=list)
    accounts: list[AccountSnapshot] = field(default_factory=list)
    positions: int = 0
    quote_errors: list[str] = field(default_factory=list)
    account_errors: int = 0
    positions_errors: int = 0
    poller: Any = None

    def bind_poller(self, p): self.poller = p
    def subscribed_symbols(self) -> set[str]: return self.symbols
    def dispatch_tick(self, symbol, snap): self.ticks.append((symbol, snap))
    def dispatch_account(self, snap): self.accounts.append(snap)
    def dispatch_positions(self): self.positions += 1
    def dispatch_quote_error(self, symbol): self.quote_errors.append(symbol)
    def dispatch_account_error(self): self.account_errors += 1
    def dispatch_positions_error(self): self.positions_errors += 1


def _client(mt5_module) -> MT5Client:
    c = MT5Client(mt5_module=mt5_module)
    c.connect()
    return c


def _streaming_cfg(**overrides) -> StreamingSection:
    base = dict(
        quote_poll_interval_ms=200,
        account_poll_interval_ms=1000,
        positions_poll_interval_ms=1000,
    )
    base.update(overrides)
    return StreamingSection(**base)


def test_poller_start_stop_is_idempotent():
    fake = FakeMT5()
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp, config=_streaming_cfg())
    p.start()
    p.start()  # idempotent
    p.stop()
    p.stop()  # idempotent


def test_poller_polls_subscribed_symbol_and_dispatches_initial_tick():
    fake = FakeMT5()
    fake._symbol_info_tick["EURUSD"] = FakeTick(time=1, bid=1.10, ask=1.11)
    disp = RecordingDispatcher(symbols={"EURUSD"})
    p = Poller(client=_client(fake), dispatcher=disp, config=_streaming_cfg())
    p.poll_once()  # synchronous test helper: one full cycle, no thread
    assert len(disp.ticks) == 1
    sym, snap = disp.ticks[0]
    assert sym == "EURUSD"
    assert snap.bid == 1.10


def test_poller_skips_when_no_symbols_subscribed():
    fake = FakeMT5()
    disp = RecordingDispatcher(symbols=set())
    p = Poller(client=_client(fake), dispatcher=disp, config=_streaming_cfg())
    p.poll_once()
    assert disp.ticks == []


def test_poller_dispatches_account_on_balance_change():
    fake = FakeMT5()
    fake._account_info = FakeAccountInfo(balance=10_000.0, credit=0.0, currency="USD")
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(account_poll_interval_ms=100))
    p.poll_once()
    assert len(disp.accounts) == 1  # initial diff (None vs first snapshot)
    fake._account_info = FakeAccountInfo(balance=10_500.0, credit=0.0, currency="USD")
    # Wait long enough for the cadence guard to allow a second account poll.
    time.sleep(0.20)
    p.poll_once()
    assert len(disp.accounts) == 2


def test_poller_skips_account_when_only_equity_changed():
    fake = FakeMT5()
    fake._account_info = FakeAccountInfo(balance=10_000.0, equity=10_010.0, currency="USD")
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(account_poll_interval_ms=100))
    p.poll_once()
    n = len(disp.accounts)
    fake._account_info = FakeAccountInfo(balance=10_000.0, equity=10_999.0, currency="USD")
    time.sleep(0.20)
    p.poll_once()
    assert len(disp.accounts) == n  # equity-only drift does NOT fire


def test_poller_dispatches_positions_on_open_close():
    fake = FakeMT5()
    fake._positions_get = ()
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=100))
    p.poll_once()
    initial = disp.positions
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0),)
    time.sleep(0.20)
    p.poll_once()
    assert disp.positions == initial + 1
    fake._positions_get = ()
    time.sleep(0.20)
    p.poll_once()
    assert disp.positions == initial + 2


def test_poller_dispatches_positions_on_sl_change():
    fake = FakeMT5()
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0),)
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=100))
    p.poll_once()
    initial = disp.positions
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=1.05, tp=0.0),)
    time.sleep(0.20)
    p.poll_once()
    assert disp.positions == initial + 1


def test_poller_skips_positions_when_only_floating_pnl_changed():
    fake = FakeMT5()
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0, profit=4.0),)
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=100))
    p.poll_once()
    initial = disp.positions
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0, profit=99.0),)
    time.sleep(0.20)
    p.poll_once()
    assert disp.positions == initial  # profit-only drift does NOT fire
