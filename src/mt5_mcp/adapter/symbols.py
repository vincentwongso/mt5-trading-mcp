"""Symbol preparation pipeline — selects, validates, caches.

Hides mt5lib's sharp edges described in §10.1 of the architecture doc:
  - symbol_info() returning None for unknown names
  - needing symbol_select() before quote/trade calls
  - broker-specific filling-mode bitmasks
  - volume step / min / max arithmetic
  - price quantisation to `point`
"""

from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail


_CACHE_TTL_S = 60.0

# Indirection so tests can monkeypatch the clock.
def _monotonic() -> float:
    return _time.monotonic()


@dataclass
class _CacheEntry:
    info: Any
    expires_at: float


class SymbolPrep:
    def __init__(self, client: MT5Client) -> None:
        self._client = client
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()

    # --- public API ------------------------------------------------------

    def get(self, symbol: str) -> Any:
        """Return a populated `symbol_info` (post-select). Raises if unknown."""
        with self._lock:
            hit = self._cache.get(symbol)
            if hit is not None and hit.expires_at > _monotonic():
                return hit.info
        info = self._client.mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_FOUND",
                message=f"Symbol '{symbol}' not found on this broker.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol},
            ))
        if not getattr(info, "visible", True):
            ok = self._client.mt5.symbol_select(symbol, True)
            if not ok:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_ENABLED",
                    message=f"Could not enable symbol '{symbol}' in Market Watch.",
                    retryable=True,
                    requires_human=False,
                    details={"symbol": symbol},
                ))
            info = self._client.mt5.symbol_info(symbol)
            if info is None:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_FOUND",
                    message=f"Symbol '{symbol}' vanished after select.",
                    retryable=False,
                    requires_human=True,
                    details={"symbol": symbol},
                ))
        with self._lock:
            self._cache[symbol] = _CacheEntry(info, _monotonic() + _CACHE_TTL_S)
        return info

    def validate_volume(self, symbol: str, volume: Decimal) -> None:
        info = self.get(symbol)
        vmin = Decimal(str(info.volume_min))
        vmax = Decimal(str(info.volume_max))
        vstep = Decimal(str(info.volume_step))
        if volume < vmin:
            raise MT5Error(ErrorDetail(
                code="INVALID_VOLUME",
                message=f"Volume {volume} below min {vmin} for {symbol}.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol, "volume": str(volume), "min": str(vmin)},
            ))
        if volume > vmax:
            raise MT5Error(ErrorDetail(
                code="INVALID_VOLUME",
                message=f"Volume {volume} above max {vmax} for {symbol}.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol, "volume": str(volume), "max": str(vmax)},
            ))
        # Step check: (volume - vmin) must be a multiple of vstep within quantise tolerance.
        ratio = (volume - vmin) / vstep
        if ratio != ratio.to_integral_value():
            raise MT5Error(ErrorDetail(
                code="INVALID_VOLUME",
                message=f"Volume {volume} is not a multiple of step {vstep} for {symbol}.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol, "volume": str(volume), "step": str(vstep)},
            ))

    def quantise_price(self, symbol: str, price: Decimal) -> Decimal:
        info = self.get(symbol)
        digits = int(info.digits)
        q = Decimal(1).scaleb(-digits)  # e.g. digits=5 → 0.00001
        return price.quantize(q, rounding=ROUND_HALF_UP)

    def pick_filling_mode(
        self,
        symbol: str,
        *,
        order_type: Literal["market", "limit", "stop", "stop_limit"],
    ) -> int:
        info = self.get(symbol)
        mask = int(info.filling_mode)
        mt5 = self._client.mt5
        # For market orders prefer IOC, fall back to FOK. RETURN is invalid for market.
        # For pending orders, RETURN is the canonical choice.
        if order_type == "market":
            preferences = (
                (mt5.SYMBOL_FILLING_IOC, mt5.ORDER_FILLING_IOC),
                (mt5.SYMBOL_FILLING_FOK, mt5.ORDER_FILLING_FOK),
            )
        else:
            # Pending orders: RETURN preferred; fall back to IOC then FOK.
            preferences = (
                (4, mt5.ORDER_FILLING_RETURN),
                (mt5.SYMBOL_FILLING_IOC, mt5.ORDER_FILLING_IOC),
                (mt5.SYMBOL_FILLING_FOK, mt5.ORDER_FILLING_FOK),
            )
        for advertised_bit, order_filling in preferences:
            if mask & advertised_bit:
                return order_filling
        raise MT5Error(ErrorDetail(
            code="INVALID_FILLING_MODE",
            message=f"Symbol {symbol} accepts no filling mode compatible with {order_type}.",
            retryable=False,
            requires_human=True,
            details={"symbol": symbol, "filling_mode_mask": mask},
        ))

    def invalidate(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                self._cache.pop(symbol, None)
