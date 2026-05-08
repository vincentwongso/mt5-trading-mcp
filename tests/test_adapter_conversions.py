"""Type marshalling + broker-TZ→UTC conversion."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from mt5_mcp.adapter.conversions import (
    account_info_from_raw,
    deal_from_raw,
    epoch_to_utc,
    infer_broker_tz_offset,
    order_from_raw,
    position_from_raw,
    quote_from_tick,
    symbol_info_from_raw,
    terminal_info_from_raw,
)
from tests.fakes import (
    FakeAccountInfo,
    FakeDeal,
    FakeOrder,
    FakePosition,
    FakeSymbolInfo,
    FakeTerminalInfo,
    FakeTick,
)


def test_epoch_to_utc_removes_broker_offset():
    # Broker is GMT+3 (EET summer). A broker-time epoch of 2026-04-21T13:00
    # interpreted as naive corresponds to a real UTC of 2026-04-21T10:00.
    # mt5lib encodes "broker 13:00" as the epoch that UTC-labels it 13:00.
    epoch_naive = int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    dt = epoch_to_utc(epoch_naive, broker_offset_minutes=180)
    assert dt.tzinfo is timezone.utc
    assert dt == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)


def test_epoch_to_utc_handles_zero_offset():
    epoch = int(datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc).timestamp())
    assert epoch_to_utc(epoch, 0) == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)


def test_infer_broker_tz_offset_rounds_to_quarter_hour():
    # mt5lib stores broker-13:00 as epoch labelled 13:00 UTC
    broker_ts = int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())  # broker says 13:00
    real_utc = datetime(2026, 4, 21, 10, 2, tzinfo=timezone.utc)  # truly 10:02Z
    offset = infer_broker_tz_offset(broker_ts, real_utc)
    assert offset == 180  # rounded to 15-min


def test_infer_broker_tz_offset_handles_negative_tz():
    broker_ts = int(datetime(2026, 4, 21, 5, 0, tzinfo=timezone.utc).timestamp())  # broker says 05:00
    real_utc = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    offset = infer_broker_tz_offset(broker_ts, real_utc)
    assert offset == -300  # GMT-5


def test_position_from_raw_converts_decimals_and_time():
    raw = FakePosition(
        ticket=99, symbol="EURUSD", type=0, volume=0.1,
        price_open=1.0820, price_current=1.0824, sl=0.0, tp=0.0,
        profit=4.0, swap=0.0,
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        comment="",
    )
    pos = position_from_raw(raw, broker_offset_minutes=180)
    assert pos.type == "buy"
    assert pos.volume == Decimal("0.1")
    assert pos.time_open == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert pos.sl is None and pos.tp is None  # 0.0 → None
    assert pos.comment is None  # "" → None


def test_position_sell_type():
    raw = FakePosition(type=1)
    pos = position_from_raw(raw, broker_offset_minutes=0)
    assert pos.type == "sell"


def test_account_info_from_raw():
    raw = FakeAccountInfo(margin_mode=0)
    info = account_info_from_raw(raw)
    assert info.margin_mode == "retail_netting"
    assert info.balance == Decimal("10000.0")
    # margin_level should pass through
    assert info.margin_level is not None


def test_account_margin_mode_values():
    raw = FakeAccountInfo(margin_mode=1)
    assert account_info_from_raw(raw).margin_mode == "exchange"
    raw = FakeAccountInfo(margin_mode=2)
    assert account_info_from_raw(raw).margin_mode == "retail_hedging"


def test_quote_from_tick():
    tick = FakeTick(time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()), bid=1.08, ask=1.09)
    q = quote_from_tick(tick, symbol="EURUSD", broker_offset_minutes=180)
    assert q.time == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert q.bid == Decimal("1.08")


def test_symbol_info_from_raw_derives_category():
    raw = FakeSymbolInfo(path="Forex\\Majors\\EURUSD", filling_mode=1 | 2)  # FOK|IOC
    info = symbol_info_from_raw(raw)
    assert info.category == "Forex"
    assert set(info.filling_modes) == {"fok", "ioc"}


def test_symbol_info_tradeable_flag():
    raw = FakeSymbolInfo(trade_mode=0)  # disabled
    assert symbol_info_from_raw(raw).is_tradeable is False
    raw = FakeSymbolInfo(trade_mode=4)  # full
    assert symbol_info_from_raw(raw).is_tradeable is True


def test_symbol_info_calc_mode_mapping():
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=0)).calc_mode == "forex"
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=2)).calc_mode == "cfd"
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=3)).calc_mode == "cfd_index"
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=4)).calc_mode == "cfd_leverage"
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=32)).calc_mode == "exch_stocks"
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=64)).calc_mode == "serv_collateral"
    # Out-of-band → "unknown" (defensive).
    assert symbol_info_from_raw(FakeSymbolInfo(trade_calc_mode=999)).calc_mode == "unknown"


def test_symbol_info_swap_mode_mapping():
    assert symbol_info_from_raw(FakeSymbolInfo(swap_mode=0)).swap_mode == "disabled"
    assert symbol_info_from_raw(FakeSymbolInfo(swap_mode=1)).swap_mode == "by_points"
    assert symbol_info_from_raw(FakeSymbolInfo(swap_mode=4)).swap_mode == "by_deposit_currency"
    assert symbol_info_from_raw(FakeSymbolInfo(swap_mode=99)).swap_mode == "unknown"


def test_symbol_info_triple_swap_weekday_mapping():
    assert symbol_info_from_raw(FakeSymbolInfo(swap_rollover3days=3)).triple_swap_weekday == "wednesday"
    assert symbol_info_from_raw(FakeSymbolInfo(swap_rollover3days=5)).triple_swap_weekday == "friday"
    assert symbol_info_from_raw(FakeSymbolInfo(swap_rollover3days=0)).triple_swap_weekday == "sunday"
    # Out-of-range falls back to wednesday (the FX convention).
    assert symbol_info_from_raw(FakeSymbolInfo(swap_rollover3days=99)).triple_swap_weekday == "wednesday"


def test_symbol_info_tick_value_fields():
    raw = FakeSymbolInfo(
        trade_tick_value=1.0,
        trade_tick_value_profit=1.05,
        trade_tick_value_loss=0.95,
    )
    info = symbol_info_from_raw(raw)
    assert info.tick_value == Decimal("1.0")
    assert info.tick_value_profit == Decimal("1.05")
    assert info.tick_value_loss == Decimal("0.95")


def test_symbol_info_swap_rates_passed_through():
    raw = FakeSymbolInfo(swap_long=-2.5, swap_short=0.8, swap_mode=4)
    info = symbol_info_from_raw(raw)
    assert info.swap_long == Decimal("-2.5")
    assert info.swap_short == Decimal("0.8")
    assert info.swap_mode == "by_deposit_currency"


def test_symbol_info_margin_fields_passed_through():
    raw = FakeSymbolInfo(
        margin_initial=1000.0,
        margin_maintenance=500.0,
        margin_hedged=50.0,
    )
    info = symbol_info_from_raw(raw)
    assert info.margin_initial == Decimal("1000.0")
    assert info.margin_maintenance == Decimal("500.0")
    assert info.margin_hedged == Decimal("50.0")


def test_symbol_info_stops_and_freeze_levels():
    raw = FakeSymbolInfo(trade_stops_level=20, trade_freeze_level=10)
    info = symbol_info_from_raw(raw)
    assert info.stops_level == 20
    assert info.freeze_level == 10


def test_rate_from_raw_converts_attribute_access():
    from mt5_mcp.adapter.conversions import rate_from_raw
    from tests.fakes import FakeRate

    raw = FakeRate(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        open=1.0820, high=1.0830, low=1.0815, close=1.0825,
        tick_volume=100, spread=1, real_volume=0,
    )
    bar = rate_from_raw(raw, broker_offset_minutes=180)
    assert bar.time == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert bar.open == Decimal("1.082")
    assert bar.high == Decimal("1.083")
    assert bar.tick_volume == 100
    assert bar.spread == 1


def test_rate_from_raw_handles_dict_style_indexing():
    """numpy structured array rows are dict-indexable; converter must accept it."""
    from mt5_mcp.adapter.conversions import rate_from_raw

    class _DictRow:
        def __init__(self, d): self._d = d
        def __getitem__(self, k): return self._d[k]

    row = _DictRow({
        "time": int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5,
        "tick_volume": 200, "spread": 2, "real_volume": 50,
    })
    bar = rate_from_raw(row, broker_offset_minutes=0)
    assert bar.close == Decimal("100.5")
    assert bar.real_volume == 50


def test_calc_margin_result_from_raw():
    from mt5_mcp.adapter.conversions import calc_margin_result_from_raw

    result = calc_margin_result_from_raw(
        100.50,
        symbol="EURUSD",
        side="buy",
        volume=Decimal("0.1"),
        price=Decimal("1.0824"),
        deposit_currency="USD",
    )
    assert result.symbol == "EURUSD"
    assert result.side == "buy"
    assert result.margin == Decimal("100.50")
    assert result.currency == "USD"


def test_order_from_raw_maps_type():
    raw = FakeOrder(type=2)  # BUY_LIMIT
    o = order_from_raw(raw, broker_offset_minutes=0)
    assert o.type == "buy_limit"


def test_deal_from_raw_handles_balance_type():
    raw = FakeDeal(type=2)  # mt5 DEAL_TYPE_BALANCE
    d = deal_from_raw(raw, broker_offset_minutes=0)
    assert d.type == "balance"


def test_terminal_info_from_raw():
    raw = FakeTerminalInfo(build=4150)
    t = terminal_info_from_raw(
        raw,
        login=123,
        server="S",
        broker_offset_minutes=180,
        latency_ms=12,
    )
    assert t.broker_tz_offset_minutes == 180
    assert t.latency_ms == 12


def test_order_request_to_mt5_dict_market_buy(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.10"), deviation=15)
    info = FakeSymbolInfo(name="EURUSD", point=0.00001, digits=5,
                         filling_mode=1 | 2)
    out = order_request_to_mt5_dict(
        req, symbol_info=info, filling_mode=fake_mt5.ORDER_FILLING_IOC,
        price=Decimal("1.0824"), mt5=fake_mt5,
    )
    assert out["action"] == fake_mt5.TRADE_ACTION_DEAL
    assert out["symbol"] == "EURUSD"
    assert out["volume"] == 0.10
    assert out["type"] == fake_mt5.ORDER_TYPE_BUY
    assert out["price"] == 1.0824
    assert out["deviation"] == 15
    assert out["type_filling"] == fake_mt5.ORDER_FILLING_IOC


def test_order_request_to_mt5_dict_limit_sell_includes_sl_tp(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="sell", type="limit",
                       volume=Decimal("0.50"), price=Decimal("1.0900"),
                       sl=Decimal("1.0950"), tp=Decimal("1.0850"),
                       comment="strat-1")
    info = FakeSymbolInfo()
    out = order_request_to_mt5_dict(
        req, symbol_info=info, filling_mode=fake_mt5.ORDER_FILLING_RETURN,
        price=Decimal("1.0900"), mt5=fake_mt5,
    )
    assert out["action"] == fake_mt5.TRADE_ACTION_PENDING
    assert out["type"] == fake_mt5.ORDER_TYPE_SELL_LIMIT
    assert out["sl"] == 1.0950
    assert out["tp"] == 1.0850
    assert out["comment"] == "strat-1"


def test_order_result_from_mt5_response_filled():
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_result_from_mt5_response
    from tests.fakes import FakeOrderSendResult, TRADE_RETCODE_DONE

    raw = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE, order=12345, deal=999,
                              volume=0.1, price=1.0824)
    result = order_result_from_mt5_response(
        raw, action="place_order", symbol="EURUSD",
        request_volume=Decimal("0.1"),
        request_echo={"symbol": "EURUSD"},
    )
    assert result.success is True
    assert result.ticket == 12345
    assert result.action == "place_order"
    assert result.price_filled == Decimal("1.0824")
    assert result.server_response_code == TRADE_RETCODE_DONE
    assert result.error is None


def test_order_result_from_mt5_response_rejected():
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_result_from_mt5_response
    from tests.fakes import FakeOrderSendResult, TRADE_RETCODE_REJECT

    raw = FakeOrderSendResult(retcode=TRADE_RETCODE_REJECT, comment="server says no")
    result = order_result_from_mt5_response(
        raw, action="place_order", symbol="EURUSD",
        request_volume=Decimal("0.1"),
        request_echo={"symbol": "EURUSD"},
    )
    assert result.success is False
    assert result.ticket is None
    assert result.error is not None
    assert result.error.code == "REJECTED_BY_SERVER"
    assert result.server_response_code == TRADE_RETCODE_REJECT


def test_order_result_from_mt5_response_none_raw():
    """mt5lib returns None when it rejects the request before sending it.

    Older versions of this code did int(raw.retcode) without checking, so a
    None response surfaced as INTERNAL_ERROR: "NoneType has no attribute
    retcode" via the @error_envelope decorator. We now produce a typed
    MT5_NULL_RESPONSE envelope so callers can distinguish broker failures
    from library/terminal failures.
    """
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_result_from_mt5_response

    result = order_result_from_mt5_response(
        None, action="modify_order", symbol="XAGUSD",
        request_volume=Decimal("0.49"),
        request_echo={"ticket": 88384786, "sl": "78.674"},
    )
    assert result.success is False
    assert result.ticket is None
    assert result.action == "modify_order"
    assert result.symbol == "XAGUSD"
    assert result.volume == Decimal("0.49")
    assert result.price_filled is None
    assert result.server_response_code == 0
    assert result.error is not None
    assert result.error.code == "MT5_NULL_RESPONSE"
    assert "None" in result.error.message


def test_order_result_from_mt5_response_partial_fill():
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_result_from_mt5_response
    from tests.fakes import FakeOrderSendResult

    raw = FakeOrderSendResult(retcode=10010, order=12345, deal=999,
                              volume=0.05, price=1.0824)
    result = order_result_from_mt5_response(
        raw, action="place_order", symbol="EURUSD",
        request_volume=Decimal("0.10"),  # requested 0.10
        request_echo={"symbol": "EURUSD", "volume": "0.10"},
    )
    assert result.success is True            # partial fill is still a success
    assert result.ticket == 12345
    assert result.volume == Decimal("0.05")  # actual filled, not requested
    assert result.error is None
    assert result.server_response_code == 10010
