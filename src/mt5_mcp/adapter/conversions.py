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
        commission=_d(raw.commission),
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
    return SymbolInfo(
        name=raw.name,
        description=raw.description,
        category=_category_from_path(getattr(raw, "path", "")),
        contract_size=_d(raw.trade_contract_size),
        tick_size=_d(raw.point),
        volume_min=_d(raw.volume_min),
        volume_max=_d(raw.volume_max),
        volume_step=_d(raw.volume_step),
        currency_profit=str(raw.currency_profit),
        currency_margin=raw.currency_margin,
        filling_modes=_filling_modes_from_mask(raw.filling_mode),
        digits=raw.digits,
        is_tradeable=raw.trade_mode != _TRADE_MODE_DISABLED,
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
    from mt5_mcp.types import OrderResult

    retcode = int(raw.retcode)
    success = retcode == 10009  # TRADE_RETCODE_DONE — published mt5lib constant
    error = None if success else error_for_retcode(retcode, message=str(raw.comment or ""))
    return OrderResult(
        success=success,
        ticket=int(raw.order) if success and raw.order else None,
        action=action,
        symbol=symbol,
        volume=request_volume,
        price_filled=Decimal(str(raw.price)) if success and raw.price else None,
        request_echo=request_echo,
        replayed=False,
        error=error,
        server_response_code=retcode,
    )
