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


def internal_error(exc: BaseException) -> ErrorDetail:
    """Envelope for an unexpected exception escaping a tool body.

    The full traceback is logged server-side; the envelope surfaces only
    the exception type and message so an operator can triage without the
    server leaking file paths or local state to the MCP client.
    """
    return ErrorDetail(
        code="INTERNAL_ERROR",
        message=f"Unexpected {type(exc).__name__}: {exc}",
        retryable=False,
        requires_human=True,
        details={"exception_type": type(exc).__name__},
    )


def terminal_not_connected_error(
    *,
    why: str | None = None,
    raw_error: tuple[int, str] | None = None,
) -> ErrorDetail:
    """Canonical 'MT5 terminal is not connected' ErrorDetail.

    Used by both the adapter (during connect failure) and read tools
    (when terminal_info() returns None mid-session). Keeps wording
    identical so agents see one message regardless of where it surfaced.
    """
    details: dict[str, Any] | None = None
    if why or raw_error is not None:
        details = {}
        if why:
            details["why"] = why
        if raw_error is not None:
            details["raw_error"] = raw_error
    return ErrorDetail(
        code="TERMINAL_NOT_CONNECTED",
        message="MT5 terminal is not connected. Please open MT5 and log into your broker.",
        retryable=False,
        requires_human=True,
        details=details,
    )


class MT5Error(Exception):
    """Raised by the adapter when a call fails. Carries the structured detail."""

    def __init__(self, detail: ErrorDetail) -> None:
        super().__init__(f"{detail.code}: {detail.message}")
        self.detail = detail
