"""Tool registry — each subsequent task adds a register_* function here."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register every Phase 1 read tool on `mcp`."""
    from mt5_mcp.tools import account, history, market, orders, positions, system

    system.register(mcp)
    account.register(mcp)
    market.register(mcp)
    positions.register(mcp)
    orders.register(mcp)
    history.register(mcp)
