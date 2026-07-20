"""Market tools: get_quote, get_symbols, get_market_hours, get_rates, calc_margin."""

from __future__ import annotations

import platform
from decimal import Decimal
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP, Image
from pydantic import Field

from mt5_mcp.adapter.conversions import (
    calc_margin_result_from_raw,
    quote_from_tick,
    rate_from_raw,
    symbol_info_from_raw,
)
from mt5_mcp.adapter.screenshot import capture_chart
from mt5_mcp.annotations import (
    MAX_ANNOTATIONS,
    Annotation,
    serialize_annotations,
    validate_annotations,
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
        ``None`` in v1 - parsing ``symbol_info().sessions_quotes`` is
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

    @error_envelope
    def _capture_chart_screenshot(
        symbol: str,
        timeframe: str,
        annotations: Annotated[list[Annotation], Field(max_length=MAX_ANNOTATIONS)] | None = None,
    ) -> Image:
        """Windows-only body of get_chart_screenshot (needs a terminal connection)."""
        if timeframe not in _TIMEFRAME_ATTRS:
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
        # Validate before any terminal work so a bad annotation costs nothing.
        parsed = validate_annotations(annotations)
        ctx = get_context()
        # Raises SYMBOL_NOT_FOUND / SYMBOL_NOT_ENABLED, matching get_rates.
        ctx.symbols.get(symbol)
        cfg = ctx.config.screenshot
        png = capture_chart(
            ctx.client,
            symbol=symbol,
            timeframe_name=timeframe,
            width=cfg.width,
            height=cfg.height,
            template=cfg.template,
            annotation_lines=serialize_annotations(
                parsed, broker_offset_minutes=ctx.client.broker_offset_minutes
            ),
            timeout_s=cfg.timeout_s,
        )
        return Image(data=png, format="png")

    @mcp.tool()
    def get_chart_screenshot(
        symbol: str,
        timeframe: str,
        annotations: Annotated[list[Annotation], Field(max_length=MAX_ANNOTATIONS)] | None = None,
    ) -> Image:
        """PNG screenshot of the native MT5 chart for ``symbol`` at ``timeframe``.

        Windows-only: needs a GUI terminal running the AgentScreenshot EA.
        ``timeframe`` is one of ``M1``, ``M5``, ``M15``, ``M30``, ``H1``,
        ``H4``, ``D1``, ``W1``, ``MN1``. Returns an image the caller can read
        visually (candles, support/resistance, patterns).

        ``annotations`` optionally marks up the chart before capture (at most
        16). The markup is drawn on a temporary chart that is destroyed right
        after the screenshot, so it never touches the user's own charts.

        - ``{"type": "hline", "price": 2650.0, "role": "resistance"}``
        - ``{"type": "vline", "time": "2026-07-19T12:30:00Z", "text": "CPI"}``
        - ``{"type": "text", "time": ..., "price": 2612.0, "text": "note"}``
        - ``{"type": "label", "corner": "top_left", "text": "summary note"}``
        - ``{"type": "trendline", "time1": ..., "price1": 2590.0,
          "time2": ..., "price2": 2648.0, "role": "support"}``

        ``role`` is ``resistance`` (red), ``support`` (lime), ``note``
        (yellow, default) or ``neutral`` (gray dashed); ``color`` overrides it.
        Times are UTC and must be real bar timestamps from ``get_rates``, not
        guesses, or the annotation lands off-screen. Prices outside the
        visible range and times older than the visible window are accepted
        but will not appear either, since the capture shows roughly the most
        recent screen of bars.
        """
        # The platform guard MUST run before any terminal connection. This tool
        # is registered on all platforms so agents can discover it, but it only
        # works on a GUI Windows terminal. error_envelope eagerly connects
        # (ensure_connected) before the wrapped body, so a guard placed inside
        # it would be masked by TERMINAL_NOT_CONNECTED on a host with no
        # reachable terminal - which is exactly the non-Windows case here.
        host = platform.system()
        if host != "Windows":
            return {"error": ErrorDetail(
                code="SCREENSHOT_NOT_SUPPORTED",
                message=(
                    "Chart screenshots require a GUI MetaTrader 5 terminal on "
                    "Windows with the AgentScreenshot EA attached. This host is "
                    f"{host}."
                ),
                retryable=False,
                requires_human=True,
                details={"platform": host},
            ).model_dump(mode="json")}
        return _capture_chart_screenshot(
            symbol=symbol, timeframe=timeframe, annotations=annotations
        )

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
        # Select the symbol into Market Watch and surface SYMBOL_NOT_FOUND for
        # unknown symbols; the returned info is not needed here.
        ctx.symbols.get(symbol)
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
