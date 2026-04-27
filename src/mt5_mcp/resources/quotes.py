"""quotes://{symbol} resource.

Read path returns a Quote (same Pydantic model as the get_quote tool).
Subscribe hooks are wired in a later task.

NOTE: Unlike tools, resource handlers do NOT use @error_envelope. They
raise MT5Error directly and FastMCP renders the MCP-protocol error
response. Resources still call get_context() and ctx.client.call(...)
the same way tools do.

FastMCP URI-template resources: the {symbol} placeholder in the URI
string is extracted by ResourceTemplate.matches(uri) and passed as a
kwarg to the handler function. The handler is registered via
@mcp.resource("quotes://{symbol}") and receives symbol: str directly.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import quote_from_tick
from mt5_mcp.errors import MT5Error, resource_not_found
from mt5_mcp.server import get_context
from mt5_mcp.types import Quote


def register(mcp: FastMCP) -> None:
    @mcp.resource("quotes://{symbol}")
    def read_quote(symbol: str) -> Quote:
        """Current bid/ask/last for a symbol."""
        ctx = get_context()
        ctx.client.connect()
        try:
            ctx.symbols.get(symbol)
        except MT5Error:
            raise MT5Error(resource_not_found(f"quotes://{symbol}"))
        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is None:
            raise MT5Error(resource_not_found(f"quotes://{symbol}"))
        return quote_from_tick(
            tick,
            symbol=symbol,
            broker_offset_minutes=ctx.client.broker_offset_minutes,
        )
