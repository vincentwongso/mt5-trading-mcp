"""Schema and validation tests for chart annotations."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.annotations import (
    MAX_ANNOTATIONS,
    MAX_TEXT_LEN,
    HLine,
    ScreenLabel,
    validate_annotations,
)
from mt5_mcp.errors import MT5Error

T = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def test_none_and_empty_yield_empty_list():
    assert validate_annotations(None) == []
    assert validate_annotations([]) == []


def test_parses_each_annotation_type():
    out = validate_annotations([
        {"type": "hline", "price": "2650.5", "role": "resistance"},
        {"type": "vline", "time": T, "text": "CPI"},
        {"type": "text", "time": T, "price": "2612", "text": "failed breakout"},
        {"type": "label", "corner": "top_left", "text": "choppy"},
        {"type": "trendline", "time1": T, "price1": "2590",
         "time2": T, "price2": "2648", "role": "support"},
    ])
    assert [a.type for a in out] == ["hline", "vline", "text", "label", "trendline"]
    assert out[0].price == Decimal("2650.5")


def test_defaults_role_to_note_and_color_to_none():
    (a,) = validate_annotations([{"type": "hline", "price": "1"}])
    assert a.role == "note"
    assert a.color is None


def test_rejects_unknown_role_naming_the_index():
    with pytest.raises(MT5Error) as ei:
        validate_annotations([
            {"type": "hline", "price": "1"},
            {"type": "hline", "price": "2"},
            {"type": "hline", "price": "3", "role": "resistence"},
        ])
    assert ei.value.detail.code == "INVALID_ANNOTATION"
    assert ei.value.detail.retryable is False
    assert "2" in ei.value.detail.message      # zero-based index of the bad entry
    assert "role" in ei.value.detail.message


def test_rejects_pipe_and_newline_in_text():
    for bad in ("a|b", "a\nb", "a\rb"):
        with pytest.raises(MT5Error) as ei:
            validate_annotations([{"type": "text", "time": T, "price": "1", "text": bad}])
        assert ei.value.detail.code == "INVALID_ANNOTATION"


def test_rejects_overlong_and_empty_text():
    for bad in ("x" * (MAX_TEXT_LEN + 1), ""):
        with pytest.raises(MT5Error):
            validate_annotations([{"type": "text", "time": T, "price": "1", "text": bad}])
    # Exactly at the cap is accepted.
    ok = validate_annotations(
        [{"type": "text", "time": T, "price": "1", "text": "x" * MAX_TEXT_LEN}]
    )
    assert len(ok) == 1


def test_rejects_more_than_max_annotations():
    too_many = [{"type": "hline", "price": str(i)} for i in range(MAX_ANNOTATIONS + 1)]
    with pytest.raises(MT5Error) as ei:
        validate_annotations(too_many)
    assert ei.value.detail.code == "INVALID_ANNOTATION"
    assert str(MAX_ANNOTATIONS) in ei.value.detail.message
    # Exactly at the cap is accepted.
    assert len(validate_annotations(too_many[:MAX_ANNOTATIONS])) == MAX_ANNOTATIONS


def test_rejects_non_finite_price():
    for bad in ("NaN", "Infinity"):
        with pytest.raises(MT5Error):
            validate_annotations([{"type": "hline", "price": bad}])


def test_rejects_unknown_type_and_unknown_field():
    with pytest.raises(MT5Error):
        validate_annotations([{"type": "rectangle", "price": "1"}])
    with pytest.raises(MT5Error):
        validate_annotations([{"type": "hline", "price": "1", "colour": "red"}])


def test_text_and_label_require_text():
    with pytest.raises(MT5Error):
        validate_annotations([{"type": "text", "time": T, "price": "1"}])
    with pytest.raises(MT5Error):
        validate_annotations([{"type": "label"}])


def test_models_are_constructible_directly():
    assert HLine(type="hline", price=Decimal("1")).role == "note"
    assert ScreenLabel(type="label", text="hi").corner == "top_left"
