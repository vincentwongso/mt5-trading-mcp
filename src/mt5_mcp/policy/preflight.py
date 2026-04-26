"""Pre-flight limit checks. UX optimisation, not a security control —
the broker's MT5 server enforces the real boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from mt5_mcp.config import Config
from mt5_mcp.errors import exceeds_local_limit_error
from mt5_mcp.types import ErrorDetail


@dataclass
class PreflightInputs:
    """Per-call snapshot the engine passes in.

    `notional` is the resolved notional in account currency for the
    request being attempted (computed by the tool from volume × ref-price).
    `running_daily_realised_pnl` is the day-to-date P&L sum (negative when
    losing). `estimated_realised_loss_on_close` is populated for
    close_position requests; the engine uses it to compare against
    `max_realised_loss_per_close` (also negative when realising a loss).
    """

    notional: Decimal
    running_daily_realised_pnl: Decimal = Decimal("0")
    estimated_realised_loss_on_close: Decimal = Decimal("0")


Action = Literal["place_order", "modify_order", "cancel_order", "close_position"]


def check_preflight_limits(
    action: Action,
    request: Any,
    inputs: PreflightInputs,
    config: Config,
) -> ErrorDetail | None:
    """Return an EXCEEDS_LOCAL_LIMIT ErrorDetail on refusal, None otherwise."""
    if action == "cancel_order":
        return None  # cancels reduce exposure; never refused locally

    symbol = getattr(request, "symbol", None)

    # Symbol allow/denylist (skip when symbol is unknown — modify/close use ticket).
    if symbol is not None:
        if symbol in config.symbols.denylist:
            return exceeds_local_limit_error(
                limit_name="denylist", configured=",".join(config.symbols.denylist),
                attempted=symbol,
            )
        if config.symbols.allowlist and symbol not in config.symbols.allowlist:
            return exceeds_local_limit_error(
                limit_name="allowlist", configured=",".join(config.symbols.allowlist),
                attempted=symbol,
            )

    # max_notional_per_trade — applies only to actions that ADD exposure.
    if action == "place_order" and config.policy.max_notional_per_trade > 0:
        if inputs.notional > config.policy.max_notional_per_trade:
            return exceeds_local_limit_error(
                limit_name="max_notional_per_trade",
                configured=config.policy.max_notional_per_trade,
                attempted=inputs.notional,
            )

    # Daily loss cap — applies to place_order only. Compared against the
    # absolute value of running realised P&L (which is negative when losing).
    # Once realised losses meet the cap, no new trade is permitted today.
    if action == "place_order" and config.policy.max_daily_loss > 0:
        loss_so_far = -inputs.running_daily_realised_pnl  # positive when losing
        if loss_so_far >= config.policy.max_daily_loss:
            return exceeds_local_limit_error(
                limit_name="max_daily_loss",
                configured=config.policy.max_daily_loss,
                attempted=loss_so_far,
            )

    # Realised-loss-on-close cap — close_position only.
    if action == "close_position" and config.policy.max_realised_loss_per_close > 0:
        loss_on_close = -inputs.estimated_realised_loss_on_close
        if loss_on_close > config.policy.max_realised_loss_per_close:
            return exceeds_local_limit_error(
                limit_name="max_realised_loss_per_close",
                configured=config.policy.max_realised_loss_per_close,
                attempted=loss_on_close,
            )

    return None
