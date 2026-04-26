"""Order tools: get_orders.

Phase 2 adds place_order / modify_order / cancel_order here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import order_from_raw
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import Order


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_orders(symbol: str | None = None) -> list[Order]:
        """Pending orders, optionally filtered to a single symbol."""
        ctx = get_context()
        raws = ctx.client.mt5.orders_get(symbol=symbol) if symbol else ctx.client.mt5.orders_get()
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [order_from_raw(r, broker_offset_minutes=offset) for r in raws]
