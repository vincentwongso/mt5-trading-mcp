"""Account tool: get_account_info."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import account_info_from_raw
from mt5_mcp.errors import MT5Error, terminal_not_connected_error
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import AccountInfo


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_account_info() -> AccountInfo:
        """Balance, equity, margin, leverage, currency, margin mode."""
        ctx = get_context()
        raw = ctx.client.call(lambda m: m.account_info())
        if raw is None:
            raise MT5Error(terminal_not_connected_error())
        return account_info_from_raw(raw)
