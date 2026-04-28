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
        tick_value=Decimal("1"),
        tick_value_profit=Decimal("1"),
        tick_value_loss=Decimal("1"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.01"),
        currency_profit="USD",
        currency_margin="USD",
        filling_modes=["ioc", "fok"],
        digits=5,
        is_tradeable=True,
        calc_mode="forex",
        margin_initial=Decimal("0"),
        margin_maintenance=Decimal("0"),
        margin_hedged=Decimal("0"),
        swap_long=Decimal("-2.5"),
        swap_short=Decimal("0.8"),
        swap_mode="by_deposit_currency",
        triple_swap_weekday="wednesday",
        stops_level=10,
        freeze_level=0,
    )
    assert s.category == "Forex"
    assert s.calc_mode == "forex"
    assert s.swap_long == Decimal("-2.5")


def test_terminal_info_fields():
    t = TerminalInfo(
        connected=True,
        build=4150,
        name="MetaTrader 5",
        company="FintrixMarkets Ltd",
        login=123456,
        server="FintrixMarkets-Demo",
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


def test_quote_rejects_float_bid():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Quote(
            symbol="EURUSD",
            bid=1.0823,  # float — must be Decimal
            ask=Decimal("1.0824"),
            time=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
        )


def test_account_info_rejects_float_balance():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AccountInfo(
            login=1,
            name="x",
            server="s",
            currency="USD",
            balance=100.5,  # float — must be Decimal
            equity=Decimal("100.5"),
            margin=Decimal("0"),
            margin_free=Decimal("100.5"),
            margin_level=None,
            leverage=100,
            trade_allowed=True,
            margin_mode="retail_netting",
        )


def test_position_rejects_non_utc_datetime():
    import pytest
    from datetime import timezone, timedelta
    from pydantic import ValidationError

    athens = timezone(timedelta(hours=3))  # EET summer
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
            time_open=datetime(2026, 4, 21, 10, 0, tzinfo=athens),  # non-UTC aware
            comment=None,
        )


def test_order_request_rejects_float_volume():
    import pytest
    from pydantic import ValidationError
    from mt5_mcp.types import OrderRequest

    with pytest.raises(ValidationError):
        OrderRequest(symbol="EURUSD", side="buy", type="market", volume=0.1)


def test_order_request_market_allows_no_price():
    from mt5_mcp.types import OrderRequest

    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    assert req.price is None
    assert req.deviation == 10
    assert req.approval_confirmed is False


def test_order_result_replayed_defaults_false():
    from mt5_mcp.types import OrderResult

    r = OrderResult(success=True, ticket=42, action="place_order", symbol="EURUSD",
                    volume=Decimal("0.1"), price_filled=Decimal("1.0823"),
                    request_echo={"x": 1}, server_response_code=10009)
    assert r.replayed is False


def test_approval_preview_serialises_decimals_as_strings():
    import json
    from mt5_mcp.types import ApprovalPreview, Quote

    p = ApprovalPreview(
        request_id="01HX0000000000000000000000",
        expires_at=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
        summary="BUY 0.5 EURUSD @ market",
        action="place_order", symbol="EURUSD",
        notional=Decimal("54000.00"), estimated_margin=Decimal("540.00"),
        reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                              ask=Decimal("1.0824"),
                              time=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)),
        request_echo={"x": 1},
    )
    blob = json.loads(p.model_dump_json())
    assert blob["notional"] == "54000.00"
    assert blob["reference_quote"]["bid"] == "1.0823"


def test_modify_order_request_optional_fields_default_none():
    from mt5_mcp.types import ModifyOrderRequest

    r = ModifyOrderRequest(ticket=12345)
    assert r.sl is None and r.tp is None and r.price is None
    assert r.approval_confirmed is False


def test_cancel_order_request_no_approval_fields():
    from mt5_mcp.types import CancelOrderRequest

    r = CancelOrderRequest(ticket=12345)
    # cancel_order has NO approval fields by design (reduces exposure).
    assert not hasattr(r, "approval_confirmed")
    assert not hasattr(r, "approval_request_id")


def test_close_position_request_rejects_float_volume():
    import pytest
    from pydantic import ValidationError
    from mt5_mcp.types import ClosePositionRequest

    with pytest.raises(ValidationError):
        ClosePositionRequest(ticket=1, volume=0.5)


def test_close_position_request_full_close_defaults():
    from mt5_mcp.types import ClosePositionRequest

    r = ClosePositionRequest(ticket=99999)
    assert r.volume is None              # None = close in full
    assert r.approval_confirmed is False
    assert r.approval_request_id is None
