"""check_preflight_limits - hard refusal layer (no approval can override)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mt5_mcp.config import Config, PolicySection, SymbolsSection
from mt5_mcp.policy.preflight import PreflightInputs, check_preflight_limits
from mt5_mcp.types import (
    CancelOrderRequest, ClosePositionRequest, ModifyOrderRequest, OrderRequest,
)


def _config(*, max_notional="100000", max_realised_loss="500", max_daily_loss="2000",
            allow=None, deny=None) -> Config:
    return Config(
        policy=PolicySection(
            auto_approve_notional=Decimal("1000"),
            max_notional_per_trade=Decimal(max_notional),
            max_realised_loss_per_close=Decimal(max_realised_loss),
            max_daily_loss=Decimal(max_daily_loss),
        ),
        symbols=SymbolsSection(allowlist=allow or [], denylist=deny or []),
    )


def _inputs(*, notional="100", running_daily_pnl="0", realised_loss_on_close="0") -> PreflightInputs:
    return PreflightInputs(
        notional=Decimal(notional),
        running_daily_realised_pnl=Decimal(running_daily_pnl),
        estimated_realised_loss_on_close=Decimal(realised_loss_on_close),
    )


def test_under_all_limits_passes():
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits("place_order", req, _inputs(), _config())
    assert err is None


def test_blocks_when_notional_above_max_per_trade():
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("1.0"))
    err = check_preflight_limits(
        "place_order", req, _inputs(notional="150000"),
        _config(max_notional="100000"),
    )
    assert err is not None
    assert err.code == "EXCEEDS_LOCAL_LIMIT"
    assert err.details["limit_name"] == "max_notional_per_trade"


def test_blocks_when_symbol_in_denylist():
    req = OrderRequest(symbol="XAUUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req, _inputs(),
        _config(deny=["XAUUSD"]),
    )
    assert err is not None
    assert err.details["limit_name"] == "denylist"


def test_blocks_when_allowlist_set_and_symbol_missing():
    req = OrderRequest(symbol="GBPJPY", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req, _inputs(),
        _config(allow=["EURUSD", "USDJPY"]),
    )
    assert err is not None
    assert err.details["limit_name"] == "allowlist"


def test_blocks_when_running_daily_loss_at_or_above_cap():
    """Once realised daily loss meets the cap, no new trades are allowed.

    The cap is about realised drawdown - notional doesn't enter the
    decision because notional is not equal to the trade's potential loss.
    """
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req,
        _inputs(running_daily_pnl="-2050"),  # over the 2000 cap
        _config(max_daily_loss="2000"),
    )
    assert err is not None
    assert err.details["limit_name"] == "max_daily_loss"


def test_passes_when_daily_loss_below_cap():
    """A trade goes through when realised loss hasn't yet hit the cap,
    regardless of the new trade's notional."""
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req,
        _inputs(running_daily_pnl="-1500", notional="50000"),  # large notional
        _config(max_daily_loss="2000"),
    )
    assert err is None  # at -1500 with 2000 cap, even a 50k notional trade is OK


def test_close_position_blocks_when_realised_loss_above_per_close_cap():
    req = ClosePositionRequest(ticket=42)
    err = check_preflight_limits(
        "close_position", req,
        _inputs(realised_loss_on_close="-750"),
        _config(max_realised_loss="500"),
    )
    assert err is not None
    assert err.details["limit_name"] == "max_realised_loss_per_close"


def test_cancel_order_skips_all_checks():
    req = CancelOrderRequest(ticket=42)
    err = check_preflight_limits(
        "cancel_order", req, _inputs(notional="0"),
        _config(deny=["EURUSD"]),
    )
    assert err is None


def test_modify_order_does_not_use_max_notional_per_trade():
    req = ModifyOrderRequest(ticket=42)
    err = check_preflight_limits(
        "modify_order", req, _inputs(notional="999999"),
        _config(max_notional="1000"),
    )
    assert err is None
