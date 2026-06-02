"""Shared tool helpers: error envelope, lazy-connect guard."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from mt5_mcp.errors import MT5Error, internal_error
from mt5_mcp.server import AppContext, get_context
from mt5_mcp.types import ErrorDetail


logger = logging.getLogger(__name__)


R = TypeVar("R")


def ensure_connected(ctx: AppContext) -> ErrorDetail | None:
    """Connect on first use; return an ErrorDetail if that fails."""
    try:
        ctx.client.connect()
    except MT5Error as exc:
        return exc.detail
    return None


def error_envelope(fn: Callable[..., R]) -> Callable[..., Any]:
    """Wrap a tool handler so failures become a structured ``{"error": ...}``.

    The wrapped function must accept **no** positional ``ctx`` argument -
    it should call ``get_context()`` internally.  The envelope:

    1. Calls ``get_context()`` and ``ensure_connected`` before invoking ``fn``.
    2. Catches ``MT5Error`` (the adapter's structured failure) and emits
       the carried ``ErrorDetail``.
    3. Catches any other ``Exception`` as ``INTERNAL_ERROR``, logging the
       traceback server-side so a Python stack never reaches the client.
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
        except Exception as exc:
            logger.exception("Unhandled exception in tool %s", fn.__name__)
            return {"error": internal_error(exc).model_dump(mode="json")}

    return _wrapped
