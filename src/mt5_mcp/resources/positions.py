"""positions://current resource.

Returns the same list[Position] Pydantic models as the get_positions tool.
Resource handlers do NOT use @error_envelope (see resources/quotes.py).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import position_from_raw
from mt5_mcp.server import get_context
from mt5_mcp.types import Position


def register(mcp: FastMCP) -> None:
    @mcp.resource("positions://current")
    def read_positions() -> list[Position]:
        """Currently open positions."""
        ctx = get_context()
        ctx.client.connect()
        raws = ctx.client.call(lambda m: m.positions_get())
        if raws is None:
            return []
        return [
            position_from_raw(r, broker_offset_minutes=ctx.client.broker_offset_minutes)
            for r in raws
        ]
