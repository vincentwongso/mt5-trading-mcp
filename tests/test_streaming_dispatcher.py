from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mt5_mcp.streaming.dispatcher import (
    Dispatcher,
    Subscriber,
    SubscriptionHandle,
)
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


@dataclass
class FakeSubscriber:
    """In-memory subscriber that records every notify_updated() call."""
    notifications: list[str] = field(default_factory=list)
    raise_on_send: bool = False

    def notify_updated(self, uri: str) -> None:
        if self.raise_on_send:
            raise RuntimeError("connection dead")
        self.notifications.append(uri)


@dataclass
class FakePoller:
    """In-memory poller that records add_symbol/remove_symbol/start/stop."""
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    started: int = 0
    stopped: int = 0

    def add_symbol(self, symbol: str) -> None:
        self.added.append(symbol)

    def remove_symbol(self, symbol: str) -> None:
        self.removed.append(symbol)

    def start(self) -> None:
        self.started += 1

    def stop(self, timeout: float = 2.0) -> None:
        self.stopped += 1


def _disp() -> tuple[Dispatcher, FakePoller]:
    poller = FakePoller()
    d = Dispatcher()
    d.bind_poller(poller)
    return d, poller


def test_subscribe_returns_handle_and_starts_poller_on_first():
    d, poller = _disp()
    sub = FakeSubscriber()
    h = d.subscribe("quotes://EURUSD", sub)
    assert isinstance(h, SubscriptionHandle)
    assert poller.added == ["EURUSD"]
    assert poller.started == 1


def test_second_subscribe_same_symbol_does_not_re_add_or_re_start():
    d, poller = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    d.subscribe("quotes://EURUSD", s1)
    d.subscribe("quotes://EURUSD", s2)
    assert poller.added == ["EURUSD"]   # one add only
    assert poller.started == 1          # one start only


def test_unsubscribe_removes_symbol_when_refcount_zero():
    d, poller = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    h1 = d.subscribe("quotes://EURUSD", s1)
    h2 = d.subscribe("quotes://EURUSD", s2)
    d.unsubscribe(h1)
    assert poller.removed == []         # still one subscriber
    d.unsubscribe(h2)
    assert poller.removed == ["EURUSD"]
    assert poller.stopped == 1          # last subscription gone


def test_dispatch_tick_fans_out_only_to_matching_uri():
    d, _ = _disp()
    eu, gu = FakeSubscriber(), FakeSubscriber()
    d.subscribe("quotes://EURUSD", eu)
    d.subscribe("quotes://GBPUSD", gu)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))
    assert eu.notifications == ["quotes://EURUSD"]
    assert gu.notifications == []


def test_dispatch_tick_fans_out_to_multiple_subscribers_of_same_symbol():
    d, _ = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    d.subscribe("quotes://EURUSD", s1)
    d.subscribe("quotes://EURUSD", s2)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))
    assert s1.notifications == ["quotes://EURUSD"]
    assert s2.notifications == ["quotes://EURUSD"]


def test_subscribed_symbols_returns_current_set():
    d, _ = _disp()
    d.subscribe("quotes://EURUSD", FakeSubscriber())
    d.subscribe("quotes://GBPUSD", FakeSubscriber())
    assert d.subscribed_symbols() == {"EURUSD", "GBPUSD"}
