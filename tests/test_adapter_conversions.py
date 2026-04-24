"""Type marshalling + broker-TZ→UTC conversion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        profit=4.0, swap=0.0, commission=0.0,
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
