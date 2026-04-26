"""Shared tool helpers: error envelope, lazy-connect guard."""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from mt5_mcp.errors import MT5Error
from mt5_mcp.server import AppContext, get_context
from mt5_mcp.types import ErrorDetail


R = TypeVar("R")


def ensure_connected(ctx: AppContext) -> ErrorDetail | None:
    """Connect on first use; return an ErrorDetail if that fails."""
    try:
        ctx.client.connect()
    except MT5Error as exc:
        return exc.detail
    return None


def error_envelope(fn: Callable[..., R]) -> Callable[..., Any]:
    """Wrap a tool handler so MT5Error becomes ``{"error": {...}}``.

    The wrapped function must accept **no** positional ``ctx`` argument —
    it should call ``get_context()`` internally.  The envelope:

    1. Calls ``get_context()`` and ``ensure_connected`` before invoking ``fn``.
    2. Catches any ``MT5Error`` raised by ``fn`` and converts it to the
       ``{"error": {...}}`` dict, preserving the type hint on ``fn`` so
       FastMCP does not try to serialize ``AppContext`` as a tool parameter.
    """

    @functools.wraps(fn)
    def _wrapped(**kwargs: Any) -> Any:
        ctx = get_context()
        err = ensure_connected(ctx)
        if err is not None:
            return {"error": err.model_dump(mode="json")}
        try:
            return fn(**kwargs)
        except MT5Error as exc:
            return {"error": exc.detail.model_dump(mode="json")}

    return _wrapped
