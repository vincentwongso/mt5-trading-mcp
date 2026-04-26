"""History tool: get_history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import deal_from_raw
from mt5_mcp.errors import MT5Error
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import Deal, ErrorDetail


def _parse_utc(raw: str, field: str) -> datetime:
    try:
        # fromisoformat accepts '+00:00' but not 'Z' until 3.11; handle both.
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise MT5Error(ErrorDetail(
            code="INVALID_TIMESTAMP",
            message=f"{field} is not a valid ISO 8601 timestamp: {raw}",
            retryable=False, requires_human=False,
        )) from exc
    if dt.tzinfo is None:
        raise MT5Error(ErrorDetail(
            code="INVALID_TIMESTAMP",
            message=f"{field} must be timezone-aware UTC (use '...Z' or '+00:00').",
            retryable=False, requires_human=False,
        ))
    return dt.astimezone(timezone.utc)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_history(
        from_ts: str,
        to_ts: str,
        symbol: str | None = None,
    ) -> list[Deal]:
        """Closed deals (trades) within [from_ts, to_ts]. Timestamps must be ISO 8601 UTC."""
        ctx = get_context()
        start_utc = _parse_utc(from_ts, "from_ts")
        end_utc = _parse_utc(to_ts, "to_ts")
        if end_utc <= start_utc:
            raise MT5Error(ErrorDetail(
                code="INVALID_TIMESTAMP",
                message="to_ts must be strictly after from_ts.",
                retryable=False, requires_human=False,
            ))
        # mt5lib expects naive datetimes in broker TZ.
        offset = timedelta(minutes=ctx.client.broker_offset_minutes)
        start_broker = (start_utc + offset).replace(tzinfo=None)
        end_broker = (end_utc + offset).replace(tzinfo=None)
        kwargs = {"group": f"*{symbol}*"} if symbol else {}
        raws = ctx.client.mt5.history_deals_get(start_broker, end_broker, **kwargs)
        if raws is None:
            return []
        return [
            deal_from_raw(r, broker_offset_minutes=ctx.client.broker_offset_minutes)
            for r in raws
        ]
