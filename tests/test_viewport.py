from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mt5_mcp.errors import MT5Error
from mt5_mcp.viewport import EMPTY_VIEWPORT, Viewport, validate_viewport


def test_all_none_is_empty():
    vp = validate_viewport(scale=None, bars=None, end_time=None,
                           price_min=None, price_max=None)
    assert vp == EMPTY_VIEWPORT
    assert vp.is_empty()


def test_scale_passthrough():
    vp = validate_viewport(scale=0, bars=None, end_time=None,
                           price_min=None, price_max=None)
    assert vp.scale == 0
    assert not vp.is_empty()


def test_scale_and_bars_mutually_exclusive():
    with pytest.raises(MT5Error) as exc:
        validate_viewport(scale=2, bars=100, end_time=None,
                          price_min=None, price_max=None)
    assert exc.value.detail.code == "INVALID_VIEWPORT"


@pytest.mark.parametrize("bad", [-1, 6, 42])
def test_scale_out_of_range(bad):
    with pytest.raises(MT5Error) as exc:
        validate_viewport(scale=bad, bars=None, end_time=None,
                          price_min=None, price_max=None)
    assert exc.value.detail.code == "INVALID_VIEWPORT"


@pytest.mark.parametrize("bad", [0, -5])
def test_bars_must_be_positive(bad):
    with pytest.raises(MT5Error) as exc:
        validate_viewport(scale=None, bars=bad, end_time=None,
                          price_min=None, price_max=None)
    assert exc.value.detail.code == "INVALID_VIEWPORT"


def test_price_band_both_or_neither():
    with pytest.raises(MT5Error) as exc:
        validate_viewport(scale=None, bars=None, end_time=None,
                          price_min=2600.0, price_max=None)
    assert exc.value.detail.code == "INVALID_VIEWPORT"


def test_price_band_max_must_exceed_min():
    with pytest.raises(MT5Error) as exc:
        validate_viewport(scale=None, bars=None, end_time=None,
                          price_min=2700.0, price_max=2600.0)
    assert exc.value.detail.code == "INVALID_VIEWPORT"


def test_price_band_valid():
    vp = validate_viewport(scale=None, bars=None, end_time=None,
                           price_min=2600.0, price_max=2700.0)
    assert vp.price_min == 2600.0 and vp.price_max == 2700.0


def test_end_time_parsed_to_aware_utc():
    vp = validate_viewport(scale=None, bars=None,
                           end_time="2026-07-19T12:30:00Z",
                           price_min=None, price_max=None)
    assert vp.end_time == datetime(2026, 7, 19, 12, 30, tzinfo=timezone.utc)


def test_end_time_naive_assumed_utc():
    vp = validate_viewport(scale=None, bars=None,
                           end_time="2026-07-19T12:30:00",
                           price_min=None, price_max=None)
    assert vp.end_time == datetime(2026, 7, 19, 12, 30, tzinfo=timezone.utc)


def test_end_time_unparseable_is_invalid_timestamp():
    with pytest.raises(MT5Error) as exc:
        validate_viewport(scale=None, bars=None, end_time="not-a-date",
                          price_min=None, price_max=None)
    assert exc.value.detail.code == "INVALID_TIMESTAMP"
