"""Position tools: get_positions."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import position_from_raw
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import Position


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_positions(symbol: str | None = None) -> list[Position]:
        """Open positions, optionally filtered to a single symbol."""
        ctx = get_context()
        raws = ctx.client.mt5.positions_get(symbol=symbol) if symbol else ctx.client.mt5.positions_get()
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [position_from_raw(r, broker_offset_minutes=offset) for r in raws]
