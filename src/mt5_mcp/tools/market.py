"""Market tools: get_quote, get_symbols, get_market_hours."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import quote_from_tick, symbol_info_from_raw
from mt5_mcp.errors import MT5Error
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import ErrorDetail, MarketHours, Quote, SymbolInfo


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_quote(symbol: str) -> Quote:
        """Current bid/ask for a symbol. Prepares the symbol in Market Watch if needed."""
        ctx = get_context()
        ctx.symbols.get(symbol)  # select if hidden; raises SYMBOL_NOT_FOUND if unknown
        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_ENABLED",
                message=f"No tick data for {symbol}; market may be closed.",
                retryable=True, requires_human=False,
                details={"symbol": symbol},
            ))
        return quote_from_tick(tick, symbol=symbol, broker_offset_minutes=ctx.client.broker_offset_minutes)

    @mcp.tool()
    @error_envelope
    def get_symbols(category: str | None = None) -> list[SymbolInfo]:
        """List tradeable instruments, optionally filtered by category (e.g. 'Forex', 'Metals')."""
        ctx = get_context()
        raws = ctx.client.call(lambda m: m.symbols_get())
        out = [symbol_info_from_raw(r) for r in raws]
        if category is not None:
            out = [s for s in out if s.category.lower() == category.lower()]
        return out

    @mcp.tool()
    @error_envelope
    def get_market_hours(symbol: str) -> MarketHours:
        """Whether the given symbol's session is open right now.

        v1 limitation: ``is_open`` is derived from ``trade_mode`` (open
        when non-zero). ``next_open`` and ``next_close`` are always
        ``None`` in v1 — parsing ``symbol_info().sessions_quotes`` is
        scheduled for a later release. Agents needing precise session
        boundaries should consult their broker's published schedule.
        """
        ctx = get_context()
        info = ctx.symbols.get(symbol)
        return MarketHours(
            symbol=symbol,
            is_open=getattr(info, "trade_mode", 0) != 0,
            next_open=None,
            next_close=None,
        )
