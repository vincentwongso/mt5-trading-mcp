"""Poller: shared daemon-thread loop driving change-detection for all
three subscribable resources.

Lazy-start: only spawns the thread when the dispatcher reports it has
subscribers. Skip-on-error semantics: an MT5Error in any of the three
poll routines logs WARNING and increments a per-resource counter; three
consecutive failures fire a one-shot error notification via the
dispatcher; a successful poll silently resets the counter.
"""

from __future__ import annotations

import logging
import threading
from time import monotonic
from typing import Any

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.config import StreamingSection
from mt5_mcp.errors import MT5Error
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


logger = logging.getLogger(__name__)


_FAILURE_THRESHOLD = 3


class Poller:
    def __init__(
        self,
        *,
        client: MT5Client,
        dispatcher: Any,
        config: StreamingSection,
    ) -> None:
        self._client = client
        self._dispatcher = dispatcher
        self._cfg = config

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

        self._last_ticks: dict[str, TickSnapshot] = {}
        self._last_account: AccountSnapshot | None = None
        self._last_positions: dict[int, PositionSnapshot] = {}

        self._last_account_poll: float = 0.0
        self._last_positions_poll: float = 0.0

        self._quote_failures: dict[str, int] = {}
        self._account_failures: int = 0
        self._positions_failures: int = 0

    # ----- thread lifecycle -----

    def start(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="mt5-poller", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._thread_lock:
            t = self._thread
            if t is None:
                return
            self._stop.set()
            self._wake.set()
        t.join(timeout=timeout)
        with self._thread_lock:
            self._thread = None

    def add_symbol(self, symbol: str) -> None:
        self._wake.set()

    def remove_symbol(self, symbol: str) -> None:
        self._last_ticks.pop(symbol, None)
        self._quote_failures.pop(symbol, None)

    # ----- loop -----

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            interval = self._cfg.quote_poll_interval_ms / 1000.0
            self._wake.wait(timeout=interval)
            self._wake.clear()

    def poll_once(self) -> None:
        """One synchronous poll cycle. Public for tests; called from _run."""
        self._poll_quotes()
        # Account / positions cadences are honoured against monotonic time.
        now = monotonic()
        if now - self._last_account_poll >= self._cfg.account_poll_interval_ms / 1000.0:
            self._poll_account()
            self._last_account_poll = now
        if now - self._last_positions_poll >= self._cfg.positions_poll_interval_ms / 1000.0:
            self._poll_positions()
            self._last_positions_poll = now

    def _poll_quotes(self) -> None:
        for sym in self._dispatcher.subscribed_symbols():
            try:
                tick = self._client.call(lambda m, s=sym: m.symbol_info_tick(s))
            except MT5Error:
                self._record_quote_failure(sym)
                continue
            except Exception:
                logger.exception("unexpected exception polling %s", sym)
                self._record_quote_failure(sym)
                continue
            if tick is None:
                continue
            snap = TickSnapshot(
                time_msc=getattr(tick, "time_msc", tick.time * 1000),
                bid=tick.bid,
                ask=tick.ask,
                last=tick.last,
                volume=tick.volume,
            )
            last = self._last_ticks.get(sym)
            if last != snap:
                self._last_ticks[sym] = snap
                self._dispatcher.dispatch_tick(sym, snap)
            self._quote_failures.pop(sym, None)

    def _poll_account(self) -> None:
        try:
            info = self._client.call(lambda m: m.account_info())
        except MT5Error:
            self._record_account_failure()
            return
        except Exception:
            logger.exception("unexpected exception polling account_info")
            self._record_account_failure()
            return
        if info is None:
            return
        snap = AccountSnapshot(
            balance=info.balance,
            credit=info.credit,
            currency=info.currency,
        )
        if self._last_account != snap:
            self._last_account = snap
            self._dispatcher.dispatch_account(snap)
        self._account_failures = 0

    def _poll_positions(self) -> None:
        try:
            raws = self._client.call(lambda m: m.positions_get())
        except MT5Error:
            self._record_positions_failure()
            return
        except Exception:
            logger.exception("unexpected exception polling positions_get")
            self._record_positions_failure()
            return
        if raws is None:
            raws = ()
        new_map: dict[int, PositionSnapshot] = {
            p.ticket: PositionSnapshot(
                ticket=p.ticket, volume=p.volume, sl=p.sl, tp=p.tp,
            )
            for p in raws
        }
        if new_map != self._last_positions:
            self._last_positions = new_map
            self._dispatcher.dispatch_positions()
        self._positions_failures = 0

    def _record_account_failure(self) -> None:
        self._account_failures += 1
        if self._account_failures == _FAILURE_THRESHOLD:
            logger.warning("account poll failed %dx; firing error notification",
                           self._account_failures)
            self._dispatcher.dispatch_account_error()

    def _record_positions_failure(self) -> None:
        self._positions_failures += 1
        if self._positions_failures == _FAILURE_THRESHOLD:
            logger.warning("positions poll failed %dx; firing error notification",
                           self._positions_failures)
            self._dispatcher.dispatch_positions_error()

    def _record_quote_failure(self, symbol: str) -> None:
        n = self._quote_failures.get(symbol, 0) + 1
        self._quote_failures[symbol] = n
        if n == _FAILURE_THRESHOLD:
            logger.warning("quote poll failed %dx for %s; firing error notification", n, symbol)
            self._dispatcher.dispatch_quote_error(symbol)
