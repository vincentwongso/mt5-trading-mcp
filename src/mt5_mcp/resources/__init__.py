"""MCP resource registrations.

register_resources(mcp) is called from server.build_server alongside
register_tools. Each module exposes a register(mcp) function.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    from mt5_mcp.resources import account, positions, quotes

    quotes.register(mcp)
    account.register(mcp)
    positions.register(mcp)
