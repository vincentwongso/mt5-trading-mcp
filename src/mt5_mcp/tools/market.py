"""Market tools: get_quote, get_symbols, get_market_hours, get_rates, calc_margin."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import (
    calc_margin_result_from_raw,
    quote_from_tick,
    rate_from_raw,
    symbol_info_from_raw,
)
from mt5_mcp.errors import MT5Error
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import (
    Bar,
    CalcMarginResult,
    ErrorDetail,
    MarketHours,
    Quote,
    SymbolInfo,
)


# Keys are the human-readable timeframe strings exposed at the MCP boundary;
# values are the mt5lib `TIMEFRAME_*` constant attribute names. We resolve
# names against the live mt5 module at call time so FakeMT5 and real mt5lib
# both work without hard-coding integer values.
_TIMEFRAME_ATTRS: dict[str, str] = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}

_MAX_RATES_COUNT = 5000


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

    @mcp.tool()
    @error_envelope
    def get_rates(symbol: str, timeframe: str, count: int) -> list[Bar]:
        """OHLC bars for ``symbol`` at ``timeframe``, most recent first.

        ``timeframe``: one of ``M1``, ``M5``, ``M15``, ``M30``, ``H1``,
        ``H4``, ``D1``, ``W1``, ``MN1``. ``count`` is clamped to
        [1, 5000].
        """
        ctx = get_context()
        attr = _TIMEFRAME_ATTRS.get(timeframe)
        if attr is None:
            raise MT5Error(ErrorDetail(
                code="INVALID_TIMEFRAME",
                message=(
                    f"Unknown timeframe '{timeframe}'. Use one of: "
                    f"{', '.join(_TIMEFRAME_ATTRS.keys())}."
                ),
                retryable=False,
                requires_human=False,
                details={"timeframe": timeframe},
            ))
        if count < 1:
            raise MT5Error(ErrorDetail(
                code="INVALID_COUNT",
                message="count must be >= 1.",
                retryable=False,
                requires_human=False,
                details={"count": count},
            ))
        clamped = min(int(count), _MAX_RATES_COUNT)
        # Ensure the symbol is selected in Market Watch (raises SYMBOL_NOT_FOUND
        # / SYMBOL_NOT_ENABLED via SymbolPrep, matching get_quote semantics).
        ctx.symbols.get(symbol)
        timeframe_const = getattr(ctx.client.mt5, attr)
        rows = ctx.client.call(
            lambda m: m.copy_rates_from_pos(symbol, timeframe_const, 0, clamped)
        )
        if rows is None:
            raise MT5Error(ErrorDetail(
                code="NO_RATES_AVAILABLE",
                message=(
                    f"No bars available for {symbol} {timeframe}. The symbol "
                    "may have insufficient history on this terminal."
                ),
                retryable=True,
                requires_human=False,
                details={"symbol": symbol, "timeframe": timeframe},
            ))
        offset = ctx.client.broker_offset_minutes
        return [rate_from_raw(r, broker_offset_minutes=offset) for r in rows]

    @mcp.tool()
    @error_envelope
    def calc_margin(
        symbol: str,
        side: Literal["buy", "sell"],
        volume: Decimal,
        price: Decimal | None = None,
    ) -> CalcMarginResult:
        """Broker-authoritative margin for a hypothetical order.

        Wraps ``mt5.order_calc_margin``. If ``price`` is omitted, uses the
        current ask (buy) / bid (sell). Returned margin is in deposit
        currency.
        """
        ctx = get_context()
        info = ctx.symbols.get(symbol)
        # Resolve price from current tick when not supplied.
        if price is None:
            tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
            if tick is None:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_ENABLED",
                    message=f"No tick data for {symbol}; market may be closed.",
                    retryable=True,
                    requires_human=False,
                    details={"symbol": symbol},
                ))
            price = Decimal(str(tick.ask if side == "buy" else tick.bid))
        action_const = (
            ctx.client.mt5.ORDER_TYPE_BUY if side == "buy"
            else ctx.client.mt5.ORDER_TYPE_SELL
        )
        # Quantise volume / price to the symbol's precision before the broker
        # call. mt5lib accepts floats but is sensitive to tick-size violations.
        margin = ctx.client.call(
            lambda m: m.order_calc_margin(
                action_const, symbol, float(volume), float(price)
            )
        )
        if margin is None:
            raise MT5Error(ErrorDetail(
                code="MARGIN_CALC_FAILED",
                message=(
                    f"Broker refused margin calc for {symbol} {side} {volume} "
                    f"@ {price}. Common causes: invalid volume step, market "
                    "closed, or the symbol's calc mode requires extra params."
                ),
                retryable=True,
                requires_human=False,
                details={
                    "symbol": symbol, "side": side,
                    "volume": str(volume), "price": str(price),
                },
            ))
        deposit_currency = ctx.client.call(lambda m: m.account_info()).currency
        return calc_margin_result_from_raw(
            margin,
            symbol=symbol,
            side=side,
            volume=Decimal(str(volume)),
            price=Decimal(str(price)),
            deposit_currency=deposit_currency,
        )
