"""Convert raw MetaTrader5 types → our Pydantic models.

The `MetaTrader5` library returns naive epoch ints in broker-server time
(most retail brokers = EET). We subtract the broker offset to land on UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from mt5_mcp.types import (
    AccountInfo,
    Bar,
    CalcMarginResult,
    Deal,
    Order,
    Position,
    Quote,
    SymbolInfo,
    TerminalInfo,
)


# --- timestamps ---------------------------------------------------------

def epoch_to_utc(epoch_naive: int, broker_offset_minutes: int) -> datetime:
    """Convert a broker-time epoch (as mt5lib reports it) to aware UTC.

    `broker_offset_minutes` is the broker's timezone offset from UTC in
    minutes. GMT+3 (EET summer) is +180. The mt5lib epoch is "broker local
    time treated as UTC" — so subtracting the offset yields real UTC.
    """
    # `fromtimestamp(epoch, tz=UTC)` treats the epoch as real UTC; for mt5lib
    # that produces broker-local-time labelled UTC. We adjust.
    as_if_utc = datetime.fromtimestamp(epoch_naive, tz=timezone.utc)
    return as_if_utc - timedelta(minutes=broker_offset_minutes)


def infer_broker_tz_offset(
    broker_terminal_time: int,
    real_utc_now: datetime | None = None,
) -> int:
    """Compute broker TZ offset in minutes, rounded to 15-min steps.

    The real mt5lib returns `terminal_info().time` as a naive epoch in
    broker-server time. Comparing that epoch (interpreted as UTC) to the
    real wall-clock UTC yields the offset.
    """
    if real_utc_now is None:
        real_utc_now = datetime.now(timezone.utc)
    as_if_utc = datetime.fromtimestamp(broker_terminal_time, tz=timezone.utc)
    delta = as_if_utc - real_utc_now
    minutes = round(delta.total_seconds() / 60.0 / 15.0) * 15
    return int(minutes)


# --- Decimal helpers -----------------------------------------------------

def _d(v: Any) -> Decimal:
    """Coerce float/int/str to Decimal via its string repr to avoid 0.1-binary bugs."""
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _opt_d(v: Any) -> Decimal | None:
    """Treat 0.0 as None for sl/tp-style fields — mt5lib uses 0 to mean 'unset'."""
    if v is None or v == 0.0:
        return None
    return _d(v)


def _opt_str(v: str | None) -> str | None:
    if not v:
        return None
    return v


# --- mappings ------------------------------------------------------------

_MARGIN_MODES = {0: "retail_netting", 1: "exchange", 2: "retail_hedging"}

# mt5lib: ORDER_TYPE_* — buy/sell constants are 0/1 for market; pending are 2..7.
_ORDER_TYPES = {
    2: "buy_limit",
    3: "sell_limit",
    4: "buy_stop",
    5: "sell_stop",
    6: "buy_stop_limit",
    7: "sell_stop_limit",
}

# mt5lib: DEAL_TYPE_* — 0/1 are buy/sell; 2..8 are balance/credit/etc.
_DEAL_TYPES = {
    0: "buy",
    1: "sell",
    2: "balance",
    3: "credit",
    4: "charge",
    5: "correction",
    6: "bonus",
    7: "commission",
}

_TRADE_MODE_DISABLED = 0

# mt5lib: ENUM_SYMBOL_CALC_MODE — drives which margin / profit formula applies.
_CALC_MODES = {
    0: "forex",
    1: "futures",
    2: "cfd",
    3: "cfd_index",
    4: "cfd_leverage",
    5: "forex_no_leverage",
    32: "exch_stocks",
    33: "exch_futures",
    34: "exch_futures_forts",
    35: "exch_options",
    36: "exch_options_margin",
    37: "exch_bonds",
    38: "exch_stocks_moex",
    39: "exch_bonds_moex",
    64: "serv_collateral",
}

# mt5lib: ENUM_SYMBOL_SWAP_MODE — how overnight financing is denominated.
_SWAP_MODES = {
    0: "disabled",
    1: "by_points",
    2: "by_base_currency",
    3: "by_margin_currency",
    4: "by_deposit_currency",
    5: "by_interest_current",
    6: "by_interest_open",
    7: "by_reopen_current",
    8: "by_reopen_bid",
}

# mt5lib's `swap_rollover3days` — int 0..6 with 0 = Sunday. Default to
# Wednesday (3) when out-of-range, since that's the dominant FX convention.
_WEEKDAYS = {
    0: "sunday",
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
}


# --- converters ---------------------------------------------------------

def position_from_raw(raw: Any, *, broker_offset_minutes: int) -> Position:
    return Position(
        ticket=raw.ticket,
        symbol=raw.symbol,
        type="buy" if raw.type == 0 else "sell",
        volume=_d(raw.volume),
        price_open=_d(raw.price_open),
        price_current=_d(raw.price_current),
        sl=_opt_d(raw.sl),
        tp=_opt_d(raw.tp),
        profit=_d(raw.profit),
        swap=_d(raw.swap),
        # No `commission` — TradePosition does not expose it. See Position type.
        time_open=epoch_to_utc(raw.time, broker_offset_minutes),
        comment=_opt_str(raw.comment),
    )


def order_from_raw(raw: Any, *, broker_offset_minutes: int) -> Order:
    otype = _ORDER_TYPES.get(raw.type)
    if otype is None:
        raise ValueError(f"unsupported order type: {raw.type}")
    return Order(
        ticket=raw.ticket,
        symbol=raw.symbol,
        type=otype,
        volume=_d(raw.volume_current),
        price=_d(raw.price_open),
        sl=_opt_d(raw.sl),
        tp=_opt_d(raw.tp),
        time_setup=epoch_to_utc(raw.time_setup, broker_offset_minutes),
        expiration=(
            epoch_to_utc(raw.time_expiration, broker_offset_minutes)
            if raw.time_expiration
            else None
        ),
        comment=_opt_str(raw.comment),
    )


def deal_from_raw(raw: Any, *, broker_offset_minutes: int) -> Deal:
    dtype = _DEAL_TYPES.get(raw.type, "commission")
    return Deal(
        ticket=raw.ticket,
        order=raw.order,
        symbol=raw.symbol,
        type=dtype,
        volume=_d(raw.volume),
        price=_d(raw.price),
        profit=_d(raw.profit),
        swap=_d(raw.swap),
        commission=_d(raw.commission),
        time=epoch_to_utc(raw.time, broker_offset_minutes),
        comment=_opt_str(raw.comment),
    )


def account_info_from_raw(raw: Any) -> AccountInfo:
    return AccountInfo(
        login=raw.login,
        name=raw.name,
        server=raw.server,
        currency=raw.currency,
        balance=_d(raw.balance),
        equity=_d(raw.equity),
        margin=_d(raw.margin),
        margin_free=_d(raw.margin_free),
        margin_level=_opt_d(raw.margin_level),
        leverage=raw.leverage,
        trade_allowed=raw.trade_allowed,
        margin_mode=_MARGIN_MODES.get(raw.margin_mode, "retail_netting"),
    )


def quote_from_tick(tick: Any, *, symbol: str, broker_offset_minutes: int) -> Quote:
    return Quote(
        symbol=symbol,
        bid=_d(tick.bid),
        ask=_d(tick.ask),
        time=epoch_to_utc(tick.time, broker_offset_minutes),
    )


def _category_from_path(path: str) -> str:
    # mt5lib returns backslash-separated "Forex\\Majors\\EURUSD" etc.
    first = path.split("\\")[0] if path else ""
    return first or "Unknown"


def _filling_modes_from_mask(mask: int) -> list[str]:
    modes: list[str] = []
    if mask & 1:
        modes.append("fok")
    if mask & 2:
        modes.append("ioc")
    if mask & 4:
        modes.append("return")
    return modes


def symbol_info_from_raw(raw: Any) -> SymbolInfo:
    # `trade_tick_value_profit` / `trade_tick_value_loss` exist on real mt5lib
    # builds but a few legacy/fake variants only expose `trade_tick_value`. Fall
    # back to the single value so we don't blow up on minimal fakes.
    tick_value = _d(getattr(raw, "trade_tick_value", 0))
    tick_value_profit = _d(getattr(raw, "trade_tick_value_profit", tick_value))
    tick_value_loss = _d(getattr(raw, "trade_tick_value_loss", tick_value))
    rollover = int(getattr(raw, "swap_rollover3days", 3))
    return SymbolInfo(
        name=raw.name,
        description=raw.description,
        category=_category_from_path(getattr(raw, "path", "")),
        contract_size=_d(raw.trade_contract_size),
        tick_size=_d(raw.point),
        tick_value=tick_value,
        tick_value_profit=tick_value_profit,
        tick_value_loss=tick_value_loss,
        volume_min=_d(raw.volume_min),
        volume_max=_d(raw.volume_max),
        volume_step=_d(raw.volume_step),
        currency_profit=str(raw.currency_profit),
        currency_margin=raw.currency_margin,
        filling_modes=_filling_modes_from_mask(raw.filling_mode),
        digits=raw.digits,
        is_tradeable=raw.trade_mode != _TRADE_MODE_DISABLED,
        calc_mode=_CALC_MODES.get(int(getattr(raw, "trade_calc_mode", -1)), "unknown"),
        margin_initial=_d(getattr(raw, "margin_initial", 0)),
        margin_maintenance=_d(getattr(raw, "margin_maintenance", 0)),
        margin_hedged=_d(getattr(raw, "margin_hedged", 0)),
        swap_long=_d(getattr(raw, "swap_long", 0)),
        swap_short=_d(getattr(raw, "swap_short", 0)),
        swap_mode=_SWAP_MODES.get(int(getattr(raw, "swap_mode", -1)), "unknown"),
        triple_swap_weekday=_WEEKDAYS.get(rollover, "wednesday"),
        stops_level=int(getattr(raw, "trade_stops_level", 0)),
        freeze_level=int(getattr(raw, "trade_freeze_level", 0)),
    )


def rate_from_raw(raw: Any, *, broker_offset_minutes: int) -> Bar:
    """Convert one OHLC row (from `mt5.copy_rates_from_pos`) to a Bar.

    mt5lib returns a numpy structured array; each row exposes `time`, `open`,
    `high`, `low`, `close`, `tick_volume`, `spread`, `real_volume` either as
    attribute access (NamedTuple-like rows) or dict-style indexing.
    """
    def _get(key: str, default: Any = 0) -> Any:
        try:
            return raw[key]
        except (KeyError, TypeError, IndexError):
            return getattr(raw, key, default)

    return Bar(
        time=epoch_to_utc(int(_get("time")), broker_offset_minutes),
        open=_d(_get("open")),
        high=_d(_get("high")),
        low=_d(_get("low")),
        close=_d(_get("close")),
        tick_volume=int(_get("tick_volume", 0)),
        real_volume=int(_get("real_volume", 0)),
        spread=int(_get("spread", 0)),
    )


def calc_margin_result_from_raw(
    raw: Any,
    *,
    symbol: str,
    side: str,
    volume: Decimal,
    price: Decimal,
    deposit_currency: str,
) -> CalcMarginResult:
    """Wrap `mt5.order_calc_margin` output into the typed model.

    mt5lib returns a single float (margin in deposit currency) or None on
    failure. The `None` case is handled by the caller, which raises an
    `MT5Error` before reaching this converter.
    """
    return CalcMarginResult(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        volume=volume,
        price=price,
        margin=_d(raw),
        currency=deposit_currency,
    )


def terminal_info_from_raw(
    raw: Any,
    *,
    login: int,
    server: str,
    broker_offset_minutes: int,
    latency_ms: int,
) -> TerminalInfo:
    return TerminalInfo(
        connected=getattr(raw, "connected", True),
        build=raw.build,
        name=raw.name,
        company=raw.company,
        login=login,
        server=server,
        broker_tz_offset_minutes=broker_offset_minutes,
        latency_ms=latency_ms,
    )


# --- order request / result conversion ------------------------------------

# Map our string side+type to mt5lib's ORDER_TYPE_* enums.
def _resolve_order_type(mt5: Any, side: str, type_: str) -> int:
    table = {
        ("buy",  "market"):     mt5.ORDER_TYPE_BUY,
        ("sell", "market"):     mt5.ORDER_TYPE_SELL,
        ("buy",  "limit"):      mt5.ORDER_TYPE_BUY_LIMIT,
        ("sell", "limit"):      mt5.ORDER_TYPE_SELL_LIMIT,
        ("buy",  "stop"):       mt5.ORDER_TYPE_BUY_STOP,
        ("sell", "stop"):       mt5.ORDER_TYPE_SELL_STOP,
        ("buy",  "stop_limit"): mt5.ORDER_TYPE_BUY_STOP_LIMIT,
        ("sell", "stop_limit"): mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }
    return table[(side, type_)]


def order_request_to_mt5_dict(
    req: "OrderRequest",
    *,
    symbol_info: Any,
    filling_mode: int,
    price: Decimal,
    mt5: Any,
) -> dict[str, Any]:
    """Build the dict mt5.order_send() expects.

    `price` is the resolved limit/stop or current ask/bid for market orders.
    `filling_mode` is the resolved ORDER_FILLING_* int from SymbolPrep.
    """
    action = mt5.TRADE_ACTION_DEAL if req.type == "market" else mt5.TRADE_ACTION_PENDING
    out: dict[str, Any] = {
        "action": action,
        "symbol": req.symbol,
        "volume": float(req.volume),
        "type": _resolve_order_type(mt5, req.side, req.type),
        "price": float(price),
        "deviation": int(req.deviation),
        "type_filling": int(filling_mode),
        "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
        "magic": 0,
    }
    if req.stop_limit_price is not None:
        out["stoplimit"] = float(req.stop_limit_price)
    if req.sl is not None:
        out["sl"] = float(req.sl)
    if req.tp is not None:
        out["tp"] = float(req.tp)
    if req.comment:
        out["comment"] = req.comment
    return out


def order_result_from_mt5_response(
    raw: Any,
    *,
    action: str,
    symbol: str,
    request_volume: Decimal,
    request_echo: dict[str, Any],
) -> "OrderResult":
    """Convert mt5.order_send()'s return into a typed OrderResult."""
    from mt5_mcp.errors import error_for_retcode
    from mt5_mcp.types import ErrorDetail, OrderResult

    if raw is None:
        # mt5lib's order_send returns None when it rejects the request before
        # forwarding to the broker (e.g. invalid stops, terminal disconnected,
        # AutoTrading off). Convert to a typed envelope rather than letting an
        # AttributeError on .retcode escape as INTERNAL_ERROR.
        return OrderResult(
            success=False,
            ticket=None,
            action=action,
            symbol=symbol,
            volume=request_volume,
            price_filled=None,
            request_echo=request_echo,
            replayed=False,
            error=ErrorDetail(
                code="MT5_NULL_RESPONSE",
                message=(
                    "mt5lib order_send returned None — request rejected before "
                    "reaching the broker (check terminal connection, AutoTrading "
                    "toggle, stops_level/freeze_level, and symbol tradeability)."
                ),
                retryable=False,
                requires_human=True,
                details={"action": action, "symbol": symbol},
            ),
            server_response_code=0,  # 0 is not a real MT5 retcode; sentinel for null response
        )
    retcode = int(raw.retcode)
    # 10009 = DONE (full fill); 10010 = DONE_PARTIAL (partial fill, also a success).
    success = retcode in (10009, 10010)
    error = None if success else error_for_retcode(retcode, message=str(raw.comment or ""))
    filled_volume = (
        Decimal(str(raw.volume)) if success and raw.volume else request_volume
    )
    return OrderResult(
        success=success,
        ticket=int(raw.order) if success and raw.order else None,
        action=action,
        symbol=symbol,
        volume=filled_volume,                  # actual filled amount, not requested
        price_filled=Decimal(str(raw.price)) if success and raw.price else None,
        request_echo=request_echo,
        replayed=False,
        error=error,
        server_response_code=retcode,
    )
