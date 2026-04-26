"""System tools: ping, get_terminal_info."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import terminal_info_from_raw
from mt5_mcp.errors import MT5Error, terminal_not_connected_error
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import TerminalInfo


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def ping() -> dict[str, Any]:
        """Health check — verifies the MT5 terminal is reachable.

        Returns {"ok": bool, "latency_ms": int}. Cheap; agents should call
        this after idle periods or errors that smell like disconnection.
        """
        ctx = get_context()
        ok, ms = ctx.client.ping()
        return {"ok": ok, "latency_ms": ms}

    @mcp.tool()
    @error_envelope
    def get_terminal_info() -> TerminalInfo:
        """MT5 terminal connection state and broker TZ offset."""
        ctx = get_context()
        raw = ctx.client.mt5.terminal_info()
        if raw is None:
            raise MT5Error(terminal_not_connected_error())
        acct = ctx.client.mt5.account_info()
        _, latency = ctx.client.ping()
        return terminal_info_from_raw(
            raw,
            login=(acct.login if acct else 0),
            server=(acct.server if acct else ""),
            broker_offset_minutes=ctx.client.broker_offset_minutes,
            latency_ms=latency,
        )
