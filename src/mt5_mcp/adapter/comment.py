"""Preflight validation for the order_send `comment` field.

MT5's docs list 31 as the comment maximum; some brokers reject silently before
that for non-ASCII or control characters (em-dash, smart quotes, tabs, newlines).
A silent rejection surfaces as `order_send -> None` with no retcode, which is
indistinguishable from terminal-disconnected / AutoTrading-off / wrong filling
mode. We validate here and raise INVALID_COMMENT so the agent can shorten or
strip and retry.
"""

from __future__ import annotations

from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail

COMMENT_MAX_LEN = 31


def sanitize_comment(comment: str | None) -> str | None:
    """Trim, validate, and return a comment safe for `mt5.order_send`.

    Returns None for None / empty / whitespace-only input. Raises MT5Error
    with code=INVALID_COMMENT for length, non-ASCII, or control-char violations.
    """
    if comment is None:
        return None
    trimmed = comment.strip()
    if not trimmed:
        return None
    if len(trimmed) > COMMENT_MAX_LEN:
        raise MT5Error(_error(trimmed, reason="too_long"))
    if not trimmed.isascii():
        raise MT5Error(_error(trimmed, reason="non_ascii"))
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in trimmed):
        raise MT5Error(_error(trimmed, reason="control_char"))
    return trimmed


def _error(value: str, *, reason: str) -> ErrorDetail:
    messages = {
        "too_long": (
            f"Comment exceeds {COMMENT_MAX_LEN}-char MT5 limit; shorten and retry."
        ),
        "non_ascii": (
            "Comment contains non-ASCII characters (e.g. em-dash, smart quotes); "
            "use plain ASCII and retry."
        ),
        "control_char": (
            "Comment contains control characters (tab, newline, etc.); "
            "remove them and retry."
        ),
    }
    return ErrorDetail(
        code="INVALID_COMMENT",
        message=messages[reason],
        retryable=False,
        requires_human=False,
        details={
            "reason": reason,
            "value": value,
            "length": len(value),
            "max_length": COMMENT_MAX_LEN,
        },
    )
