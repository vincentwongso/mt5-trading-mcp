"""Approval-preview store and retry-validation rules.

The store is in-memory: previews live for at most a few minutes and a
process restart legitimately invalidates pending approvals (the human
should re-confirm against the current state of the world).

Retry validation enforces:
- Identical action / symbol / side / type / volume / ticket
- Price drift within max(0.5%, deviation_points * symbol.point)
- Preview not expired
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ulid import ULID

from mt5_mcp.errors import invalid_approval_error
from mt5_mcp.types import ApprovalPreview, ErrorDetail


def new_request_id() -> str:
    """Mint a ULID — 128-bit, time-ordered, 26-char Crockford base32."""
    return str(ULID())


class ApprovalStore:
    """In-memory single-use store for pending ApprovalPreviews."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._previews: dict[str, ApprovalPreview] = {}

    def put(self, preview: ApprovalPreview) -> None:
        with self._lock:
            self._previews[preview.request_id] = preview

    def pop(self, request_id: str) -> ApprovalPreview | None:
        """Remove and return the preview if it exists and is un-expired."""
        with self._lock:
            preview = self._previews.pop(request_id, None)
        if preview is None:
            return None
        if preview.expires_at <= datetime.now(timezone.utc):
            return None
        return preview


def validate_retry(
    request: Any,
    *,
    preview: ApprovalPreview,
    current_price: Decimal,
    point: Decimal,
) -> ErrorDetail | None:
    """Check that `request` matches the stored `preview` within tolerances.

    Returns an ErrorDetail on mismatch, None on success. The caller is
    expected to have already retrieved `preview` via ApprovalStore.pop().
    """
    if preview.expires_at <= datetime.now(timezone.utc):
        return invalid_approval_error(reason="approval expired before retry arrived")

    echo = preview.request_echo

    # Identical fields. Each request type contributes a different subset.
    # `symbol` is included: an approval for EURUSD must not be honoured
    # for GBPUSD (architecture §8.1 bait-and-switch protection).
    for field in ("symbol", "side", "type", "volume", "ticket"):
        if not hasattr(request, field):
            continue
        new_val = getattr(request, field)
        old_val = echo.get(field)
        if old_val is None:
            continue  # field not part of this preview's snapshot
        if isinstance(new_val, Decimal):
            try:
                old_dec = Decimal(str(old_val))
            except Exception:
                return invalid_approval_error(
                    reason=f"{field} stored as non-numeric in preview"
                )
            if new_val != old_dec:
                return invalid_approval_error(
                    reason=f"{field} mismatch: preview={old_val} retry={new_val}"
                )
        elif new_val != old_val:
            return invalid_approval_error(
                reason=f"{field} mismatch: preview={old_val} retry={new_val}"
            )

    # Price drift tolerance: max(0.5% of reference, deviation_points * point).
    # `deviation` comes from the snapshot — the human approved THAT slippage.
    ref_price = preview.reference_quote.ask if echo.get("side") == "buy" \
                else preview.reference_quote.bid
    pct_band = ref_price * Decimal("0.005")
    dev = int(echo.get("deviation", 0))
    dev_band = Decimal(dev) * point
    tolerance = max(pct_band, dev_band)

    if abs(current_price - ref_price) > tolerance:
        return invalid_approval_error(
            reason=(
                f"price drifted beyond tolerance: ref={ref_price} now={current_price} "
                f"tolerance={tolerance}"
            )
        )

    return None
