"""Dispatcher: subscriber registry, refcounting, and notification fanout.

The Dispatcher is the only owner of subscription state. The Poller asks
the Dispatcher for the current symbol set and calls dispatch_* when it
detects a change. Subscriber sessions are abstracted via a tiny Protocol
so the Dispatcher doesn't know about STDIO vs HTTP.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


logger = logging.getLogger(__name__)


class Subscriber(Protocol):
    """Anything capable of receiving an MCP resource-update notification."""
    def notify_updated(self, uri: str) -> None: ...


@dataclass(frozen=True)
class SubscriptionHandle:
    id: str


@dataclass
class _Subscription:
    handle: SubscriptionHandle
    uri: str
    subscriber: Subscriber
    dead: bool = False


class Dispatcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs_by_uri: dict[str, list[_Subscription]] = {}
        self._subs_by_handle: dict[SubscriptionHandle, _Subscription] = {}
        self._symbol_refcount: dict[str, int] = {}
        self._poller = None  # type: ignore[var-annotated]

    def bind_poller(self, poller) -> None:
        """Late-binding to break the Poller<->Dispatcher cycle."""
        self._poller = poller

    # ----- subscription lifecycle -----

    def subscribe(self, uri: str, subscriber: Subscriber) -> SubscriptionHandle:
        handle = SubscriptionHandle(id=uuid.uuid4().hex)
        sub = _Subscription(handle=handle, uri=uri, subscriber=subscriber)
        added_symbol: str | None = None
        was_empty: bool = False
        with self._lock:
            was_empty = not self._subs_by_handle
            self._subs_by_uri.setdefault(uri, []).append(sub)
            self._subs_by_handle[handle] = sub
            if uri.startswith("quotes://"):
                sym = uri.removeprefix("quotes://")
                self._symbol_refcount[sym] = self._symbol_refcount.get(sym, 0) + 1
                if self._symbol_refcount[sym] == 1:
                    added_symbol = sym
        if added_symbol is not None and self._poller is not None:
            self._poller.add_symbol(added_symbol)
        if was_empty and self._poller is not None:
            self._poller.start()
        return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        removed_symbol: str | None = None
        now_empty: bool = False
        with self._lock:
            sub = self._subs_by_handle.pop(handle, None)
            if sub is None:
                return
            self._subs_by_uri[sub.uri].remove(sub)
            if not self._subs_by_uri[sub.uri]:
                del self._subs_by_uri[sub.uri]
            if sub.uri.startswith("quotes://"):
                sym = sub.uri.removeprefix("quotes://")
                self._symbol_refcount[sym] -= 1
                if self._symbol_refcount[sym] == 0:
                    del self._symbol_refcount[sym]
                    removed_symbol = sym
            now_empty = not self._subs_by_handle
        if removed_symbol is not None and self._poller is not None:
            self._poller.remove_symbol(removed_symbol)
        if now_empty and self._poller is not None:
            self._poller.stop()

    def subscribed_symbols(self) -> set[str]:
        with self._lock:
            return set(self._symbol_refcount.keys())

    def subscriber_count(self, uri: str) -> int:
        """Return the number of live subscribers for *uri*. For tests."""
        with self._lock:
            return len(self._subs_by_uri.get(uri, []))

    # ----- fanout -----

    def _fanout(self, uri: str) -> None:
        with self._lock:
            targets = list(self._subs_by_uri.get(uri, ()))
        for sub in targets:
            if sub.dead:
                continue
            try:
                sub.subscriber.notify_updated(uri)
            except Exception:
                logger.warning(
                    "subscriber send failed for %s; marking dead", uri,
                    exc_info=True,
                )
                sub.dead = True

    def dispatch_tick(self, symbol: str, snap: TickSnapshot) -> None:
        self._fanout(f"quotes://{symbol}")

    def dispatch_account(self, snap: AccountSnapshot) -> None:
        self._fanout("account://current")

    def dispatch_positions(self) -> None:
        self._fanout("positions://current")

    def dispatch_quote_error(self, symbol: str) -> None:
        """Fan out an updated notification on persistent quote-poll failure.

        Subscribers re-read the resource; the read path's own ctx.client.call
        is what surfaces the underlying MT5 error envelope.
        """
        self._fanout(f"quotes://{symbol}")

    def dispatch_account_error(self) -> None:
        self._fanout("account://current")

    def dispatch_positions_error(self) -> None:
        self._fanout("positions://current")

    def reap_dead_subscribers(self) -> int:
        """Remove subscribers marked dead during fanout. Returns count reaped."""
        reaped: list[_Subscription] = []
        symbols_to_release: list[str] = []
        now_empty: bool = False
        with self._lock:
            for sub in list(self._subs_by_handle.values()):
                if not sub.dead:
                    continue
                self._subs_by_handle.pop(sub.handle, None)
                self._subs_by_uri[sub.uri].remove(sub)
                if not self._subs_by_uri[sub.uri]:
                    del self._subs_by_uri[sub.uri]
                if sub.uri.startswith("quotes://"):
                    sym = sub.uri.removeprefix("quotes://")
                    self._symbol_refcount[sym] -= 1
                    if self._symbol_refcount[sym] == 0:
                        del self._symbol_refcount[sym]
                        symbols_to_release.append(sym)
                reaped.append(sub)
            now_empty = not self._subs_by_handle
        if self._poller is not None:
            for sym in symbols_to_release:
                self._poller.remove_symbol(sym)
            if now_empty and reaped:
                self._poller.stop()
        return len(reaped)
