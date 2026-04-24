"""Roundtrip + serialisation checks for Pydantic model contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from mt5_mcp.types import (
    AccountInfo,
    Deal,
    ErrorDetail,
    MarketHours,
    Order,
    Position,
    Quote,
    SymbolInfo,
    TerminalInfo,
)


def test_account_info_serialises_decimals_as_strings():
    info = AccountInfo(
        login=1,
        name="x",
        server="s",
        currency="USD",
        balance=Decimal("100.5"),
        equity=Decimal("100.5"),
        margin=Decimal("0"),
        margin_free=Decimal("100.5"),
        margin_level=None,
        leverage=100,
        trade_allowed=True,
        margin_mode="retail_netting",
    )
    blob = json.loads(info.model_dump_json())
    assert blob["balance"] == "100.5"
    assert blob["margin_level"] is None


def test_position_rejects_float_for_volume():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Position(
            ticket=1,
            symbol="EURUSD",
            type="buy",
            volume=0.1,  # float — must be Decimal or str
            price_open=Decimal("1.0"),
            price_current=Decimal("1.0"),
            sl=None,
            tp=None,
            profit=Decimal("0"),
            swap=Decimal("0"),
            commission=Decimal("0"),
            time_open=datetime(2026, 4, 21, tzinfo=timezone.utc),
            comment=None,
        )


def test_position_datetime_must_be_aware():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Position(
            ticket=1,
            symbol="EURUSD",
            type="buy",
            volume=Decimal("0.1"),
            price_open=Decimal("1.0"),
            price_current=Decimal("1.0"),
            sl=None,
            tp=None,
            profit=Decimal("0"),
            swap=Decimal("0"),
            commission=Decimal("0"),
            time_open=datetime(2026, 4, 21),  # naive — reject
            comment=None,
        )


def test_quote_roundtrip():
    q = Quote(
        symbol="EURUSD",
        bid=Decimal("1.0823"),
        ask=Decimal("1.0824"),
        time=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
    )
    blob = json.loads(q.model_dump_json())
    assert blob["time"].endswith("Z") or blob["time"].endswith("+00:00")
    assert blob["bid"] == "1.0823"


def test_error_detail_defaults():
    e = ErrorDetail(code="TERMINAL_NOT_CONNECTED", message="x", retryable=False, requires_human=True)
    assert e.details is None
    assert e.mt5_retcode is None


def test_market_hours_fields():
    m = MarketHours(
        symbol="EURUSD",
        is_open=True,
        next_close=datetime(2026, 4, 21, 21, 0, tzinfo=timezone.utc),
        next_open=None,
    )
    assert m.is_open is True


def test_symbol_info_exposes_broker_fields():
    s = SymbolInfo(
        name="EURUSD",
        description="Euro / US Dollar",
        category="Forex",
        contract_size=Decimal("100000"),
        tick_size=Decimal("0.00001"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.01"),
        currency_profit="USD",
        currency_margin="USD",
        filling_modes=["ioc", "fok"],
        digits=5,
        is_tradeable=True,
    )
    assert s.category == "Forex"


def test_terminal_info_fields():
    t = TerminalInfo(
        connected=True,
        build=4150,
        name="MetaTrader 5",
        company="Broker Ltd",
        login=123456,
        server="Broker-Demo",
        broker_tz_offset_minutes=180,
        latency_ms=12,
    )
    assert t.broker_tz_offset_minutes == 180


def test_order_and_deal_fields():
    o = Order(
        ticket=1,
        symbol="EURUSD",
        type="buy_limit",
        volume=Decimal("0.1"),
        price=Decimal("1.08"),
        sl=None,
        tp=None,
        time_setup=datetime(2026, 4, 21, tzinfo=timezone.utc),
        expiration=None,
        comment=None,
    )
    d = Deal(
        ticket=1,
        order=1,
        symbol="EURUSD",
        type="buy",
        volume=Decimal("0.1"),
        price=Decimal("1.08"),
        profit=Decimal("5"),
        swap=Decimal("0"),
        commission=Decimal("-0.5"),
        time=datetime(2026, 4, 21, tzinfo=timezone.utc),
        comment=None,
    )
    assert o.type == "buy_limit" and d.type == "buy"
