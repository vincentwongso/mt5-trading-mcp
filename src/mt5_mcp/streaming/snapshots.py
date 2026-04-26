"""Internal snapshot dataclasses used by the Poller for diff detection.

NOT the Pydantic types returned to MCP clients — those stay in
``mt5_mcp.types`` and are produced by ``adapter/conversions.py``.
Snapshots only carry the fields the diff logic compares.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickSnapshot:
    time_msc: int
    bid: float
    ask: float
    last: float
    volume: int


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Tracks identity-style fields only.

    Excluded by design: equity, margin, free_margin, profit, margin_level —
    these drift on every tick and would defeat the purpose of subscribing
    to ``account://current``.
    """
    balance: float
    credit: float
    currency: str


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Tracks identity + structural fields only.

    Excluded by design: price_current, profit, swap, time_update — these
    drift on every tick. Subscribers compose ``positions://current`` with
    ``quotes://{symbol}`` to compute floating P&L.
    """
    ticket: int
    volume: float
    sl: float
    tp: float
