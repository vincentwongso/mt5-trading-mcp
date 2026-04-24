"""Error codes and MT5 retcode → ErrorDetail mapping."""

from __future__ import annotations

from typing import Any

from mt5_mcp.types import ErrorDetail


# Subset of mt5lib retcodes we map explicitly; full table lives in mt5lib itself.
_RETCODE_MAP: dict[int, tuple[str, str, bool, bool]] = {
    # retcode: (code, message, retryable, requires_human)
    10004: ("REQUOTE", "Price moved during execution; try again.", True, False),
    10006: ("REJECTED_BY_SERVER", "Broker server rejected the trade.", False, True),
    10014: ("INVALID_VOLUME", "Volume invalid for symbol's lot step / min / max.", False, False),
    10015: ("INVALID_PRICE", "Price invalid for this order type.", True, False),
    10018: ("MARKET_CLOSED", "Symbol's session is closed.", False, False),
    10019: ("INSUFFICIENT_MARGIN", "Not enough free margin for this trade.", False, True),
}


def error_for_retcode(
    retcode: int,
    *,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> ErrorDetail:
    """Translate an `mt5lib` retcode into a structured `ErrorDetail`."""
    mapped = _RETCODE_MAP.get(retcode)
    if mapped is None:
        return ErrorDetail(
            code="MT5_UNKNOWN_RETCODE",
            message=f"Unknown mt5lib retcode {retcode}",
            retryable=False,
            requires_human=True,
            details={"raw_message": message, **(details or {})},
            mt5_retcode=retcode,
        )
    code, default_msg, retryable, requires_human = mapped
    return ErrorDetail(
        code=code,
        message=message or default_msg,
        retryable=retryable,
        requires_human=requires_human,
        details=details,
        mt5_retcode=retcode,
    )


class MT5Error(Exception):
    """Raised by the adapter when a call fails. Carries the structured detail."""

    def __init__(self, detail: ErrorDetail) -> None:
        super().__init__(f"{detail.code}: {detail.message}")
        self.detail = detail
