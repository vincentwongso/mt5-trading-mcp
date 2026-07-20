"""Schema and validation tests for chart annotations."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.annotations import (
    COLOR_BGR,
    LABEL_BASE_X,
    LABEL_BASE_Y,
    LABEL_STEP_Y,
    MAX_ANNOTATIONS,
    MAX_TEXT_LEN,
    HLine,
    ScreenLabel,
    serialize_annotations,
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


# Role default colors, tuned for a light chart template.
FIREBRICK, NAVY, DARKSLATE, DIMGRAY = 2237106, 9109504, 5197615, 6908265


def _ser(raw, offset=0):
    return serialize_annotations(validate_annotations(raw), broker_offset_minutes=offset)


def test_serializes_hline_with_role_palette():
    assert _ser([{"type": "hline", "price": "2650.5", "role": "resistance",
                  "text": "daily R"}]) == [f"A|hline|2650.5|{FIREBRICK}|0|daily R"]


def test_neutral_role_is_gray_and_dashed():
    assert _ser([{"type": "hline", "price": "1"}]) == [f"A|hline|1|{DARKSLATE}|0|"]
    assert _ser([{"type": "hline", "price": "1", "role": "neutral"}]) == [
        f"A|hline|1|{DIMGRAY}|2|"
    ]


def test_explicit_color_overrides_role_but_not_style():
    # "lime" is an explicit opt-in for dark-template users; it is not a role
    # default, so it is looked up straight from COLOR_BGR rather than pinned
    # via a role-palette constant.
    assert _ser([{"type": "hline", "price": "1", "role": "neutral",
                  "color": "lime"}]) == [f"A|hline|1|{COLOR_BGR['lime']}|2|"]


def test_missing_text_serializes_as_trailing_empty_field():
    assert _ser([{"type": "hline", "price": "1", "role": "support"}]) == [
        f"A|hline|1|{NAVY}|0|"
    ]


def test_time_anchors_convert_to_broker_epoch():
    # 2026-07-19T12:00:00Z on a GMT+3 broker reads as 15:00 in broker time.
    utc_epoch = int(T.timestamp())
    lines = _ser([{"type": "vline", "time": T}], offset=180)
    assert lines == [f"A|vline|{utc_epoch + 3 * 3600}|{DARKSLATE}|0|"]


def test_serializes_text_and_trendline():
    e = int(T.timestamp())
    assert _ser([{"type": "text", "time": T, "price": "2612", "text": "note"}]) == [
        f"A|text|{e}|2612|{DARKSLATE}|note"
    ]
    assert _ser([{"type": "trendline", "time1": T, "price1": "2590",
                  "time2": T, "price2": "2648", "role": "support"}]) == [
        f"A|trend|{e}|2590|{e}|2648|{NAVY}|0|"
    ]


def test_labels_stack_within_a_corner_and_reset_across_corners():
    lines = _ser([
        {"type": "label", "corner": "top_left", "text": "one"},
        {"type": "label", "corner": "top_left", "text": "two"},
        {"type": "label", "corner": "top_right", "text": "three"},
    ])
    assert lines == [
        f"A|label|0|{LABEL_BASE_X}|{LABEL_BASE_Y}|{DARKSLATE}|one",
        f"A|label|0|{LABEL_BASE_X}|{LABEL_BASE_Y + LABEL_STEP_Y}|{DARKSLATE}|two",
        f"A|label|3|{LABEL_BASE_X}|{LABEL_BASE_Y}|{DARKSLATE}|three",
    ]


def test_no_line_ever_contains_a_newline():
    lines = _ser([
        {"type": "hline", "price": "1", "text": "a b c"},
        {"type": "label", "text": "d e f"},
    ])
    assert all("\n" not in ln and "\r" not in ln for ln in lines)
    assert all(ln.startswith("A|") for ln in lines)


def test_empty_input_serializes_to_no_lines():
    assert serialize_annotations([], broker_offset_minutes=0) == []


def test_round_prices_never_serialize_as_exponent_notation():
    # Decimal("100").normalize() yields Decimal('1E+2'), and MQL5's
    # StringToDouble("1E+2") silently misparses it, placing a support/resistance
    # line at the wrong price with no error. This test pins the _num() behavior
    # to ensure it always emits fixed-point notation, never exponent notation.
    assert _ser([{"type": "hline", "price": "100", "role": "resistance"}]) == [
        f"A|hline|100|{FIREBRICK}|0|"
    ]
    assert _ser([{"type": "text", "time": T, "price": "1000", "text": "big"}]) == [
        f"A|text|{int(T.timestamp())}|1000|{DARKSLATE}|big"
    ]
    assert _ser([{"type": "trendline", "time1": T, "price1": "100",
                  "time2": T, "price2": "1000", "role": "support"}]) == [
        f"A|trend|{int(T.timestamp())}|100|{int(T.timestamp())}|1000|{NAVY}|0|"
    ]
