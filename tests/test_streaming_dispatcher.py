from __future__ import annotations

from dataclasses import dataclass, field


from mt5_mcp.streaming.dispatcher import (
    Dispatcher,
    SubscriptionHandle,
)
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
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


def test_dispatch_account_fanout():
    d, _ = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    d.subscribe("account://current", s1)
    d.subscribe("account://current", s2)
    d.dispatch_account(AccountSnapshot(balance=100.0, credit=0.0, currency="USD"))
    assert s1.notifications == ["account://current"]
    assert s2.notifications == ["account://current"]


def test_dispatch_positions_fanout():
    d, _ = _disp()
    s = FakeSubscriber()
    d.subscribe("positions://current", s)
    d.dispatch_positions()
    assert s.notifications == ["positions://current"]


def test_subscribing_to_account_does_not_touch_poller_symbol_set():
    d, poller = _disp()
    d.subscribe("account://current", FakeSubscriber())
    d.subscribe("positions://current", FakeSubscriber())
    assert poller.added == []
    assert poller.started == 1  # first subscription overall starts the poller


def test_dead_subscriber_marked_after_send_failure():
    d, _ = _disp()
    bad = FakeSubscriber(raise_on_send=True)
    good = FakeSubscriber()
    d.subscribe("quotes://EURUSD", bad)
    d.subscribe("quotes://EURUSD", good)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))
    # Good subscriber still receives even though the bad one raised.
    assert good.notifications == ["quotes://EURUSD"]
    # On next dispatch, bad is skipped (no exception escapes)
    d.dispatch_tick("EURUSD", TickSnapshot(2, 1.11, 1.21, 0.0, 0))
    assert good.notifications == ["quotes://EURUSD", "quotes://EURUSD"]


def test_reap_dead_subscribers_removes_them():
    d, poller = _disp()
    bad = FakeSubscriber(raise_on_send=True)
    good = FakeSubscriber()
    d.subscribe("quotes://EURUSD", bad)
    d.subscribe("quotes://EURUSD", good)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))  # marks bad dead
    reaped = d.reap_dead_subscribers()
    assert reaped == 1
    # Refcount unchanged because good subscriber holds the symbol.
    d.dispatch_tick("EURUSD", TickSnapshot(2, 1.1, 1.2, 0.0, 0))
    assert good.notifications == ["quotes://EURUSD", "quotes://EURUSD"]


def test_reap_releases_symbol_when_last_subscriber_dies():
    d, poller = _disp()
    bad = FakeSubscriber(raise_on_send=True)
    d.subscribe("quotes://EURUSD", bad)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))  # marks dead
    d.reap_dead_subscribers()
    assert poller.removed == ["EURUSD"]
    assert poller.stopped == 1  # no subscriptions left


def test_dispatch_quote_error_fanouts_to_symbol_subscribers():
    d, _ = _disp()
    s = FakeSubscriber()
    d.subscribe("quotes://EURUSD", s)
    d.dispatch_quote_error("EURUSD")
    assert s.notifications == ["quotes://EURUSD"]


def test_dispatch_account_and_positions_error_fanouts():
    d, _ = _disp()
    sa, sp = FakeSubscriber(), FakeSubscriber()
    d.subscribe("account://current", sa)
    d.subscribe("positions://current", sp)
    d.dispatch_account_error()
    d.dispatch_positions_error()
    assert sa.notifications == ["account://current"]
    assert sp.notifications == ["positions://current"]
