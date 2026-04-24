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
from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail


logger = logging.getLogger(__name__)

# mt5lib's internal retcode indicating the library wasn't initialized for
# this call. Exact number per MetaTrader5 source.
_RES_NOT_INITIALIZED = -10004
_RES_IPC_TIMEOUT = -10003


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
            self.broker_offset_minutes = infer_broker_tz_offset(
                ti.time, datetime.now(timezone.utc)
            )
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

    def _call_with_reinit(self, fn: Callable[[], T]) -> T:
        """Invoke `fn`; if it returns None AND last_error is the
        not-initialized retcode, re-init once and retry.
        """
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
        details = {"raw_error": raw, "why": message}
        return ErrorDetail(
            code="TERMINAL_NOT_CONNECTED",
            message="MT5 terminal is not connected. Please open MT5 and log into your broker.",
            retryable=False,
            requires_human=True,
            details=details,
        )
