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
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from mt5_mcp.adapter.conversions import infer_broker_tz_offset
from mt5_mcp.errors import MT5Error, terminal_not_connected_error
from mt5_mcp.types import ErrorDetail


logger = logging.getLogger(__name__)

# mt5lib's internal retcode indicating the library wasn't initialized for
# this call. Exact number per MetaTrader5 source.
_RES_NOT_INITIALIZED = -10004


T = TypeVar("T")


def _import_mt5():
    """Import the real `MetaTrader5` module on demand.

    Split out so tests can inject a fake without touching the Windows-only
    import during non-Windows CI runs.
    """
    import MetaTrader5  # type: ignore[import]
    return MetaTrader5


class MT5Client:
    def __init__(
        self,
        *,
        terminal_path: str | None = None,
        mt5_module: Any | None = None,
    ) -> None:
        self._mt5 = mt5_module if mt5_module is not None else _import_mt5()
        self._terminal_path = terminal_path or None
        self._lock = threading.RLock()
        self._initialised = False
        self.broker_offset_minutes = 0

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
            try:
                self.broker_offset_minutes = infer_broker_tz_offset(
                    ti.time, datetime.now(timezone.utc)
                )
            except AttributeError:
                # Some MT5 builds / demo accounts omit .time from TerminalInfo.
                # Fall back to offset=0 (UTC); the server still works.
                logger.warning(
                    "terminal_info().time not available; assuming broker TZ offset = 0"
                )
                self.broker_offset_minutes = 0
            self._initialised = True
            logger.info(
                "MT5 connected; broker TZ offset = %+d min", self.broker_offset_minutes
            )

    def disconnect(self) -> None:
        with self._lock:
            if not self._initialised:
                return
            try:
                self._mt5.shutdown()
            finally:
                self._initialised = False

    # --- health ----------------------------------------------------------

    def ping(self) -> tuple[bool, int]:
        t0 = time.perf_counter()
        try:
            ti = self._mt5.terminal_info()
        except Exception:
            return False, 0
        ms = int((time.perf_counter() - t0) * 1000)
        return (ti is not None), ms

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
