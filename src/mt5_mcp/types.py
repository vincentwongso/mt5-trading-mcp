"""Pydantic models returned by MCP tools.

All money / price / volume fields are `Decimal` (JSON-encoded as string).
All datetimes are timezone-aware UTC — `adapter/conversions.py` is the only
place naive timestamps become aware.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, PlainSerializer, ValidationInfo, field_validator


# Decimals serialise as fixed-point strings (no scientific notation) in JSON
# mode; in Python mode they remain Decimal instances.  Replaces the
# deprecated `model_config.json_encoders` mechanism.
_DecimalStr = Annotated[
    Decimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json"),
]


def _annotation_mentions_decimal(ann: Any) -> bool:
    """Return True if *ann* is or contains `Decimal` (handles Optional/Union/generics)."""
    if ann is Decimal:
        return True
    # Recurse into Union / Optional / generic containers (e.g. list[Decimal]).
    for sub in get_args(ann):
        if _annotation_mentions_decimal(sub):
            return True
    return False


class _Base(BaseModel):
    model_config = ConfigDict(
        # Reject silent float→Decimal coercion; callers must pass Decimal or
        # numeric strings.
        strict=False,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _validate_common(cls, v: Any, info: ValidationInfo) -> Any:
        if isinstance(v, float):
            ann = cls.model_fields[info.field_name].annotation
            if _annotation_mentions_decimal(ann):
                raise ValueError(
                    f"{info.field_name}: use Decimal, not float, for money/price/volume"
                )
        if isinstance(v, datetime):
            if v.tzinfo is None:
                raise ValueError(f"{info.field_name}: datetime must be timezone-aware (UTC)")
            # Enforce UTC — any non-zero offset is a broker-TZ leak.
            if v.utcoffset() != timedelta(0):
                raise ValueError(f"{info.field_name}: datetime must be UTC (offset must be 0)")
        return v


class ErrorDetail(_Base):
    code: str
    message: str
    retryable: bool
    requires_human: bool
    details: dict[str, Any] | None = None
    mt5_retcode: int | None = None


class AccountInfo(_Base):
    login: int
    name: str
    server: str
    currency: str
    balance: _DecimalStr
    equity: _DecimalStr
    margin: _DecimalStr
    margin_free: _DecimalStr
    margin_level: _DecimalStr | None
    leverage: int
    trade_allowed: bool
    margin_mode: Literal["retail_netting", "exchange", "retail_hedging"]


class Position(_Base):
    ticket: int
    symbol: str
    type: Literal["buy", "sell"]
    volume: _DecimalStr
    price_open: _DecimalStr
    price_current: _DecimalStr
    sl: _DecimalStr | None
    tp: _DecimalStr | None
    profit: _DecimalStr
    swap: _DecimalStr
    commission: _DecimalStr
    time_open: datetime
    comment: str | None


class Order(_Base):
    ticket: int
    symbol: str
    type: Literal["buy_limit", "sell_limit", "buy_stop", "sell_stop", "buy_stop_limit", "sell_stop_limit"]
    volume: _DecimalStr
    price: _DecimalStr
    sl: _DecimalStr | None
    tp: _DecimalStr | None
    time_setup: datetime
    expiration: datetime | None
    comment: str | None


class Deal(_Base):
    ticket: int
    order: int
    symbol: str
    type: Literal["buy", "sell", "balance", "credit", "charge", "correction", "bonus", "commission"]
    volume: _DecimalStr
    price: _DecimalStr
    profit: _DecimalStr
    swap: _DecimalStr
    commission: _DecimalStr
    time: datetime
    comment: str | None


class Quote(_Base):
    symbol: str
    bid: _DecimalStr
    ask: _DecimalStr
    time: datetime


class SymbolInfo(_Base):
    name: str
    description: str
    category: str  # Derived from `path` — "Forex", "Indices", "Metals", "Crypto", "Stocks", or raw first path segment.
    contract_size: _DecimalStr
    tick_size: _DecimalStr
    volume_min: _DecimalStr
    volume_max: _DecimalStr
    volume_step: _DecimalStr
    currency_profit: str
    currency_margin: str
    filling_modes: list[Literal["fok", "ioc", "return"]]
    digits: int
    is_tradeable: bool


class MarketHours(_Base):
    symbol: str
    is_open: bool
    next_open: datetime | None
    next_close: datetime | None


class TerminalInfo(_Base):
    connected: bool
    build: int
    name: str
    company: str
    login: int
    server: str
    broker_tz_offset_minutes: int
    latency_ms: int


class OrderRequest(_Base):
    symbol: str
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop", "stop_limit"]
    volume: _DecimalStr
    price: _DecimalStr | None = None             # required for limit / stop / stop_limit
    stop_limit_price: _DecimalStr | None = None  # required for stop_limit only
    sl: _DecimalStr | None = None
    tp: _DecimalStr | None = None
    deviation: int = 10
    comment: str | None = None
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None


class ModifyOrderRequest(_Base):
    ticket: int
    sl: _DecimalStr | None = None
    tp: _DecimalStr | None = None
    price: _DecimalStr | None = None             # pending orders only
    expiration: datetime | None = None
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None


class CancelOrderRequest(_Base):
    ticket: int
    idempotency_key: str | None = None


class ClosePositionRequest(_Base):
    ticket: int
    volume: _DecimalStr | None = None            # None = close in full
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None


class ApprovalPreview(_Base):
    request_id: str                              # ULID (canonical 26-char Crockford base32)
    expires_at: datetime
    summary: str
    action: Literal["place_order", "modify_order", "close_position"]
    symbol: str
    notional: _DecimalStr
    estimated_margin: _DecimalStr
    reference_quote: Quote
    request_echo: dict[str, Any]


class OrderResult(_Base):
    success: bool
    ticket: int | None
    action: str
    symbol: str
    volume: _DecimalStr
    price_filled: _DecimalStr | None
    request_echo: dict[str, Any]
    replayed: bool = False
    error: ErrorDetail | None = None
    server_response_code: int
