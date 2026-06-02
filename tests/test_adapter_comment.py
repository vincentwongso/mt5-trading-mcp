"""Preflight validation for the order_send `comment` field.

MT5 brokers silently reject orders whose comment violates length/character
constraints - the call returns None and there's no retcode. v1.0.14 catches
these cases at the adapter layer and surfaces INVALID_COMMENT so the agent can
shorten/strip and retry instead of chasing the wrong failure mode.
"""

from __future__ import annotations

import pytest

from mt5_mcp.adapter.comment import COMMENT_MAX_LEN, sanitize_comment
from mt5_mcp.errors import MT5Error


# --- nullable / empty -----------------------------------------------------

def test_none_passes_through():
    assert sanitize_comment(None) is None


def test_empty_string_normalises_to_none():
    assert sanitize_comment("") is None


def test_whitespace_only_normalises_to_none():
    assert sanitize_comment("   ") is None


# --- whitespace trimming (silent, non-error) ------------------------------

def test_leading_trailing_whitespace_stripped():
    assert sanitize_comment("  stage2-abc123  ") == "stage2-abc123"


def test_clean_comment_unchanged():
    assert sanitize_comment("stage2-ef4e324a") == "stage2-ef4e324a"


def test_max_length_boundary_ok():
    s = "A" * COMMENT_MAX_LEN
    assert sanitize_comment(s) == s


# --- rejections (raise INVALID_COMMENT preflight) ------------------------

def test_too_long_raises_invalid_comment():
    over = "A" * (COMMENT_MAX_LEN + 1)
    with pytest.raises(MT5Error) as ei:
        sanitize_comment(over)
    err = ei.value.detail
    assert err.code == "INVALID_COMMENT"
    assert err.retryable is False
    assert err.details["reason"] == "too_long"
    assert err.details["max_length"] == COMMENT_MAX_LEN


def test_non_ascii_raises_invalid_comment():
    # Non-ASCII LLM punctuation (here an ellipsis; em-dashes and smart quotes
    # behave the same) is common output that brokers tend to reject.
    with pytest.raises(MT5Error) as ei:
        sanitize_comment("stage2 … abc")
    err = ei.value.detail
    assert err.code == "INVALID_COMMENT"
    assert err.details["reason"] == "non_ascii"


def test_smart_quote_raises_invalid_comment():
    with pytest.raises(MT5Error) as ei:
        sanitize_comment("stage2 “abc”")
    assert ei.value.detail.details["reason"] == "non_ascii"


def test_control_char_raises_invalid_comment():
    with pytest.raises(MT5Error) as ei:
        sanitize_comment("stage2\nabc")
    err = ei.value.detail
    assert err.code == "INVALID_COMMENT"
    assert err.details["reason"] == "control_char"


def test_tab_is_control_char():
    with pytest.raises(MT5Error) as ei:
        sanitize_comment("stage2\tabc")
    assert ei.value.detail.details["reason"] == "control_char"


def test_error_payload_includes_value_for_debug():
    over = "A" * (COMMENT_MAX_LEN + 5)
    with pytest.raises(MT5Error) as ei:
        sanitize_comment(over)
    # The agent needs to see what it sent so it can fix the call.
    assert ei.value.detail.details["value"] == over
    assert ei.value.detail.details["length"] == len(over)


# --- integration: order_request_to_mt5_dict wires it in -------------------

def test_order_request_dict_strips_whitespace_in_comment(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.10"), deviation=10,
                       comment="  strat-1  ")
    out = order_request_to_mt5_dict(
        req, symbol_info=FakeSymbolInfo(),
        filling_mode=fake_mt5.ORDER_FILLING_IOC,
        price=Decimal("1.0824"), mt5=fake_mt5,
    )
    assert out["comment"] == "strat-1"


def test_order_request_dict_drops_whitespace_only_comment(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.10"), deviation=10, comment="   ")
    out = order_request_to_mt5_dict(
        req, symbol_info=FakeSymbolInfo(),
        filling_mode=fake_mt5.ORDER_FILLING_IOC,
        price=Decimal("1.0824"), mt5=fake_mt5,
    )
    assert "comment" not in out


def test_order_request_dict_raises_on_invalid_comment(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.10"), deviation=10,
                       comment="stage2 … non-ascii")
    with pytest.raises(MT5Error) as ei:
        order_request_to_mt5_dict(
            req, symbol_info=FakeSymbolInfo(),
            filling_mode=fake_mt5.ORDER_FILLING_IOC,
            price=Decimal("1.0824"), mt5=fake_mt5,
        )
    assert ei.value.detail.code == "INVALID_COMMENT"
