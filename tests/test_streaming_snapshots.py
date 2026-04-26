import pytest

from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


def test_tick_snapshot_equality_by_value():
    a = TickSnapshot(time_msc=1, bid=1.1, ask=1.2, last=0.0, volume=0)
    b = TickSnapshot(time_msc=1, bid=1.1, ask=1.2, last=0.0, volume=0)
    c = TickSnapshot(time_msc=2, bid=1.1, ask=1.2, last=0.0, volume=0)
    assert a == b
    assert a != c


def test_tick_snapshot_is_frozen():
    a = TickSnapshot(time_msc=1, bid=1.1, ask=1.2, last=0.0, volume=0)
    with pytest.raises(Exception):  # FrozenInstanceError
        a.bid = 2.0  # type: ignore[misc]


def test_account_snapshot_tracks_only_balance_credit_currency():
    a = AccountSnapshot(balance=100.0, credit=0.0, currency="USD")
    b = AccountSnapshot(balance=100.0, credit=0.0, currency="USD")
    c = AccountSnapshot(balance=200.0, credit=0.0, currency="USD")
    assert a == b
    assert a != c


def test_position_snapshot_tracks_only_ticket_volume_sl_tp():
    a = PositionSnapshot(ticket=1, volume=0.10, sl=0.0, tp=0.0)
    b = PositionSnapshot(ticket=1, volume=0.10, sl=0.0, tp=0.0)
    c = PositionSnapshot(ticket=1, volume=0.10, sl=1.05, tp=0.0)  # SL changed
    assert a == b
    assert a != c
