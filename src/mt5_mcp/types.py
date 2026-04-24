"""Pydantic models returned by MCP tools.

All money / price / volume fields are `Decimal` (JSON-encoded as string).
All datetimes are timezone-aware UTC — `adapter/conversions.py` is the only
place naive timestamps become aware.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_JSON_OVERRIDES: dict[type, Any] = {Decimal: lambda d: format(d, "f")}


class _Base(BaseModel):
    model_config = ConfigDict(
        # Reject silent float→Decimal coercion; callers must pass Decimal or
        # numeric strings.
        strict=False,
        # Keep JSON encoders stable so `model_dump_json()` produces the
        # string-formatted Decimals promised by the architecture doc.
        json_encoders=_JSON_OVERRIDES,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _reject_naive_datetimes(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("datetime must be timezone-aware (UTC)")
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
    balance: Decimal
    equity: Decimal
    margin: Decimal
    margin_free: Decimal
    margin_level: Decimal | None
    leverage: int
    trade_allowed: bool
    margin_mode: Literal["retail_netting", "exchange", "retail_hedging"]


class Position(_Base):
    ticket: int
    symbol: str
    type: Literal["buy", "sell"]
    volume: Decimal
    price_open: Decimal
    price_current: Decimal
    sl: Decimal | None
    tp: Decimal | None
    profit: Decimal
    swap: Decimal
    commission: Decimal
    time_open: datetime
    comment: str | None

    @field_validator("volume", "price_open", "price_current", "profit", "swap", "commission", mode="before")
    @classmethod
    def _reject_float(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise ValueError("use Decimal, not float, for money/price/volume")
        return v


class Order(_Base):
    ticket: int
    symbol: str
    type: Literal["buy_limit", "sell_limit", "buy_stop", "sell_stop", "buy_stop_limit", "sell_stop_limit"]
    volume: Decimal
    price: Decimal
    sl: Decimal | None
    tp: Decimal | None
    time_setup: datetime
    expiration: datetime | None
    comment: str | None


class Deal(_Base):
    ticket: int
    order: int
    symbol: str
    type: Literal["buy", "sell", "balance", "credit", "charge", "correction", "bonus", "commission"]
    volume: Decimal
    price: Decimal
    profit: Decimal
    swap: Decimal
    commission: Decimal
    time: datetime
    comment: str | None


class Quote(_Base):
    symbol: str
    bid: Decimal
    ask: Decimal
    time: datetime


class SymbolInfo(_Base):
    name: str
    description: str
    category: str  # Derived from `path` — "Forex", "Indices", "Metals", "Crypto", "Stocks", or raw first path segment.
    contract_size: Decimal
    tick_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
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
