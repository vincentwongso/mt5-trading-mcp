"""account://current resource.

Returns the same AccountInfo Pydantic model as the get_account_info tool.
Resource handlers do NOT use @error_envelope (see resources/quotes.py).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import account_info_from_raw
from mt5_mcp.errors import MT5Error, terminal_not_connected_error
from mt5_mcp.server import get_context
from mt5_mcp.types import AccountInfo


def register(mcp: FastMCP) -> None:
    @mcp.resource("account://current")
    def read_account() -> AccountInfo:
        """Current account snapshot (balance, equity, margin, leverage, etc.)."""
        ctx = get_context()
        ctx.client.connect()
        raw = ctx.client.call(lambda m: m.account_info())
        if raw is None:
            raise MT5Error(terminal_not_connected_error(
                why="account_info() returned None mid-session",
            ))
        return account_info_from_raw(raw)
