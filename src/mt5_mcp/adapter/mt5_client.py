"""Singleton wrapper around the `MetaTrader5` Python module.

This is the ONLY module that imports `MetaTrader5`. Everything else goes
through an `MT5Client` instance, which:
  - Owns initialize / shutdown lifecycle.
  - Caches the broker's TZ offset (inferred once per connect).
  - Transparently re-initialises once if a call returns the "not
    initialized" retcode mid-session.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from mt5_mcp.adapter.conversions import infer_broker_tz_offset
from mt5_mcp.errors import MT5Error, terminal_not_connected_error
from mt5_mcp.types import ErrorDetail


logger = logging.getLogger(__name__)

# mt5lib's internal retcode indicating the library wasn't initialized for
# this call. Exact number per MetaTrader5 source.
_RES_NOT_INITIALIZED = -10004

# Symbols probed during connect() to derive the broker TZ offset when
# terminal_info().time is absent. Crypto first because BTCUSD/ETHUSD
# stream 24/7 (covers weekend connects); FX/metals/JPY-pair as weekday
# fallbacks. Adding a broker-specific symbol is a one-line edit.
_BROKER_TIME_PROBE_SYMBOLS: tuple[str, ...] = (
    "BTCUSD", "ETHUSD", "EURUSD", "XAUUSD", "USDJPY", "GBPUSD",
)

# How fresh a probe tick must be for offset inference to be trusted.
# A stale tick records broker-time-then versus real-time-now and would
# yield a wildly wrong delta. 5 minutes covers normal broker quote lag
# while rejecting weekend-stale ticks.
_FRESH_TICK_SECONDS = 5 * 60

# Plausible real-world broker TZ offset range. Real brokers run on
# server clocks between UTC-12 and UTC+14; anything outside this range
# is a sign the probe tick is N×15-min stale (the residual check below
# can't catch staleness that aligns to a 15-min boundary).
_MAX_PLAUSIBLE_OFFSET_MINUTES = 14 * 60


T = TypeVar("T")


def _import_mt5():
    """Import the real `MetaTrader5` module on demand.

    Split out so tests can inject a fake without touching the Windows-only
    import during non-Windows CI runs.
    """
    import MetaTrader5  # type: ignore[import]
    return MetaTrader5


def resolve_mt5_module(config) -> Any:
    """Resolve the MetaTrader5 backend per config.

    - No `[mt5.bridge]` block  -> native in-process import (Windows / Wine Python).
    - `[mt5.bridge]` present    -> an `mt5linux` RPyC proxy to a remote terminal
      (e.g. the gmag11/metatrader5_vnc container on Linux). The proxy exposes the
      same MetaTrader5 API, including constants (verified: RPyC passes ints by
      value), so it drops straight in as the injected module.

    This is the ONLY place, besides `_import_mt5`, that imports a backend.
    """
    bridge = config.mt5.bridge
    if bridge is None:
        try:
            return _import_mt5()
        except ImportError as exc:
            raise MT5Error(
                terminal_not_connected_error(
                    why="the MetaTrader5 package is not installed. On Windows: "
                        "pip install mt5-trading-mcp. On Linux: run MT5 in Docker "
                        "and configure [mt5.bridge] (see the README Linux setup).",
                )
            ) from exc
    try:
        from mt5linux import MetaTrader5 as _RPyCClient  # type: ignore[import]
    except ImportError as exc:
        raise MT5Error(
            terminal_not_connected_error(
                why="[mt5.bridge] is configured but no mt5linux client is "
                    "installed. Install it with: pip install "
                    "'mt5-trading-mcp[bridge]'",
            )
        ) from exc
    try:
        return _RPyCClient(host=bridge.host, port=bridge.port)
    except Exception as exc:
        raise MT5Error(
            terminal_not_connected_error(
                why=f"could not reach the MT5 bridge at "
                    f"{bridge.host}:{bridge.port}: {exc}",
            )
        ) from exc


class MT5Client:
    def __init__(
        self,
        *,
        terminal_path: str | None = None,
        mt5_module: Any | None = None,
        mt5_factory: Callable[[], Any] | None = None,
        backend_label: str = "native",
    ) -> None:
        # `mt5_module` (a pre-resolved module/proxy) is used directly — tests
        # inject FakeMT5 here. Otherwise the backend is resolved LAZILY on first
        # use via `mt5_factory` (defaulting to the native import), so the server
        # can be constructed on a host without MetaTrader5 installed.
        self._mt5_resolved = mt5_module
        self._mt5_factory = mt5_factory or _import_mt5
        self._terminal_path = terminal_path or None
        self._lock = threading.RLock()
        self._initialised = False
        self.broker_offset_minutes = 0
        self.backend_label = backend_label

    @property
    def _mt5(self) -> Any:
        """The backend module/proxy, resolved lazily on first access."""
        if self._mt5_resolved is None:
            with self._lock:
                if self._mt5_resolved is None:
                    self._mt5_resolved = self._mt5_factory()
        return self._mt5_resolved

    # --- lifecycle -------------------------------------------------------

    def connect(self) -> None:
        """Initialise the underlying library and cache broker TZ."""
        with self._lock:
            if self._initialised:
                return
            ok = (
                self._mt5.initialize(self._terminal_path)
                if self._terminal_path
                else self._mt5.initialize()
            )
            if not ok:
                raise MT5Error(self._connection_error("initialize returned False"))
            ti = self._mt5.terminal_info()
            if ti is None:
                raise MT5Error(self._connection_error("terminal_info returned None"))
            self.broker_offset_minutes = self._derive_broker_offset(ti)
            self._initialised = True
            logger.info(
                "MT5 connected; broker TZ offset = %+d min", self.broker_offset_minutes
            )

    def _derive_broker_offset(self, ti: Any) -> int:
        """Derive the broker TZ offset (minutes from UTC).

        Layered fallback — degrades gracefully so the server still starts
        when the canonical source is missing:

        1. ``terminal_info().time`` — cheap and accurate when the broker's
           MT5 build exposes it. Some builds (and most demo configurations
           we've seen) omit ``.time`` from the named tuple entirely.
        2. The freshest tick on a common always-streaming symbol. The MT5
           Python module's ``symbol_info_tick().time`` IS documented stable
           API. Validated by re-applying the inferred offset and checking
           the tick's residual age — a fresh tick on a broker at offset N
           must land within ``_FRESH_TICK_SECONDS`` of real-utc-now once
           the offset is removed; a weekend-stale tick blows that gap out
           by hours and is rejected.
        3. Zero, with a warning. Means timestamps the server emits are
           interpreted as broker-local-time-treated-as-UTC, which is
           wrong by the broker offset until the next reconnect during
           market hours.
        """
        now_utc = datetime.now(timezone.utc)

        ti_time = getattr(ti, "time", None)
        if ti_time:
            return infer_broker_tz_offset(int(ti_time), now_utc)

        for sym in _BROKER_TIME_PROBE_SYMBOLS:
            try:
                tick = self._mt5.symbol_info_tick(sym)
            except Exception:
                continue
            if tick is None:
                continue
            tick_time = getattr(tick, "time", 0) or 0
            if not tick_time:
                continue
            candidate = infer_broker_tz_offset(int(tick_time), now_utc)
            # A tick that's exactly N×15-min stale produces a candidate
            # offset that lines up with the rounding step; the residual
            # check below would accept it. Bound to plausible TZ range
            # first to close that hole.
            if abs(candidate) > _MAX_PLAUSIBLE_OFFSET_MINUTES:
                continue
            broker_now_in_utc = (
                datetime.fromtimestamp(int(tick_time), tz=timezone.utc)
                - timedelta(minutes=candidate)
            )
            residual_seconds = abs((broker_now_in_utc - now_utc).total_seconds())
            if residual_seconds <= _FRESH_TICK_SECONDS:
                logger.info(
                    "Derived broker TZ offset = %+d min from a %s tick "
                    "(terminal_info.time absent on this MT5 build).",
                    candidate, sym,
                )
                return candidate

        logger.warning(
            "Could not derive broker TZ offset (terminal_info.time absent and "
            "no fresh tick on any of %s); assuming offset = 0. Timestamps in "
            "tool outputs may be off by the broker's real offset until the "
            "market resumes streaming.",
            list(_BROKER_TIME_PROBE_SYMBOLS),
        )
        return 0

    def disconnect(self) -> None:
        with self._lock:
            if not self._initialised:
                return
            try:
                self._mt5.shutdown()
            finally:
                self._initialised = False

    # --- health ----------------------------------------------------------

    def ping(self) -> tuple[bool, int, str | None]:
        """Layered health check; reports which layer answered.

        Some MT5 builds return ``None`` from ``terminal_info()`` even when
        the terminal is fully connected and quotes/account_info both work.
        Reporting that as ``ok=false`` misleads cron/monitoring.

        Each layer routes through ``self.call()`` so a transient
        NOT_INITIALIZED state triggers a reinit attempt before the layer
        gives up — same recovery behavior as every other read tool. The
        earlier rule "ping bypasses retry to detect raw IPC state" gave
        agents a probe that lied about usability whenever the IPC needed
        a transparent reconnect; the layered fallback already provides
        per-source diagnostics via the ``via`` field, which is more
        useful in practice.

        1. ``terminal_info()`` non-None → ``via="terminal_info"``
        2. ``account_info()`` with populated ``login`` → ``via="account_info"``
        3. Fresh tick (<``_FRESH_TICK_SECONDS``) on any
           ``_BROKER_TIME_PROBE_SYMBOLS`` symbol → ``via="tick_probe"``

        Returns ``(ok, latency_ms, via)``; ``via`` is ``None`` on failure.
        """
        t0 = time.perf_counter()

        try:
            ti = self.call(lambda m: m.terminal_info())
            if ti is not None:
                return True, int((time.perf_counter() - t0) * 1000), "terminal_info"
        except Exception:
            pass

        try:
            acct = self.call(lambda m: m.account_info())
            if acct is not None and getattr(acct, "login", 0):
                return True, int((time.perf_counter() - t0) * 1000), "account_info"
        except Exception:
            pass

        now_utc = datetime.now(timezone.utc)
        for sym in _BROKER_TIME_PROBE_SYMBOLS:
            try:
                tick = self.call(lambda m: m.symbol_info_tick(sym))
            except Exception:
                continue
            if tick is None:
                continue
            tick_time = getattr(tick, "time", 0) or 0
            if not tick_time:
                continue
            broker_now_in_utc = (
                datetime.fromtimestamp(int(tick_time), tz=timezone.utc)
                - timedelta(minutes=self.broker_offset_minutes)
            )
            if abs((broker_now_in_utc - now_utc).total_seconds()) <= _FRESH_TICK_SECONDS:
                return True, int((time.perf_counter() - t0) * 1000), "tick_probe"

        return False, int((time.perf_counter() - t0) * 1000), None

    # --- call routing ---------------------------------------------------

    def call(self, fn: Callable[[Any], T]) -> T:
        """Invoke ``fn(mt5_module)`` with transparent re-init on NOT_INITIALIZED.

        The MT5 terminal can drop its IPC link mid-session (terminal restart,
        Windows wake-from-sleep, antivirus interruption). When this happens
        mt5lib returns ``None`` AND sets ``last_error()`` to ``-10004``.
        This wrapper detects that case, calls ``connect()`` once, and retries
        ``fn`` exactly once. Other ``None`` results pass through verbatim so
        callers can distinguish "no data" from "connection lost".

        Read tools route every mt5lib data call through ``call()``; only
        constant lookups (e.g. ``ctx.client.mt5.ORDER_FILLING_IOC``) and
        ``ping`` skip it.
        """
        return self._call_with_reinit(lambda: fn(self._mt5))

    def _call_with_reinit(self, fn: Callable[[], T]) -> T:
        """Invoke `fn`; if it returns None AND last_error is the
        not-initialized retcode, re-init once and retry."""
        result = fn()
        if result is not None:
            return result
        err = self._mt5.last_error()
        code = err[0] if isinstance(err, (tuple, list)) and err else 0
        if code != _RES_NOT_INITIALIZED:
            return result  # genuine None; caller will decide what it means
        logger.warning("mt5lib returned NOT_INITIALIZED; attempting re-init")
        with self._lock:
            self._initialised = False
        try:
            self.connect()
        except MT5Error:
            raise
        return fn()  # one retry; propagates whatever the second call returns

    # --- module accessor (used by symbols + tools) -----------------------

    @property
    def mt5(self) -> Any:
        return self._mt5

    # --- error helpers --------------------------------------------------

    def _connection_error(self, message: str) -> ErrorDetail:
        raw = self._mt5.last_error()
        return terminal_not_connected_error(why=message, raw_error=raw)
