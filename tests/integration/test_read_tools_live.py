"""Tier 1 read-tool integration tests against a live MT5 demo terminal.

One test per read tool. Each is marked @pytest.mark.integration so the
default pytest run excludes it. Run with `pytest -m integration -v`.

The unit suite (tests/test_tools_*.py) covers every error path against
FakeMT5; this file only validates that the live broker round-trip works
on the happy path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.integration.conftest import LiveServer, call_tool


pytestmark = pytest.mark.integration


def test_ping(live_server: LiveServer) -> None:
    out = call_tool(live_server, "ping")
    assert out["ok"] is True, f"expected ok=True, got {out}"
    assert out["latency_ms"] >= 0, f"expected non-negative latency, got {out}"


def test_get_terminal_info(live_server: LiveServer) -> None:
    out = call_tool(live_server, "get_terminal_info")
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert out.connected is True
    assert out.build > 0


def test_get_account_info(live_server: LiveServer) -> None:
    out = call_tool(live_server, "get_account_info")
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert Decimal(str(out.balance)) > 0, f"expected positive balance, got {out.balance}"
    assert isinstance(out.currency, str) and len(out.currency) >= 3
    assert out.leverage >= 1


def test_get_symbols(live_server: LiveServer, probe_symbol: str) -> None:
    out = call_tool(live_server, "get_symbols")
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert len(out) > 0
    names = {s.name for s in out}
    assert probe_symbol in names, f"{probe_symbol} not in returned symbols"


def test_get_quote(live_server: LiveServer, probe_symbol: str, market_open: None) -> None:
    out = call_tool(live_server, "get_quote", symbol=probe_symbol)
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    bid = Decimal(str(out.bid))
    ask = Decimal(str(out.ask))
    assert bid > 0, f"expected positive bid, got {bid}"
    assert ask >= bid, f"expected ask>=bid, got bid={bid} ask={ask}"
    age = datetime.now(timezone.utc) - out.time
    assert age < timedelta(minutes=5), f"tick too stale: {age.total_seconds()}s old"


def test_get_market_hours(live_server: LiveServer, probe_symbol: str) -> None:
    out = call_tool(live_server, "get_market_hours", symbol=probe_symbol)
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert out.symbol == probe_symbol
    # v1 contract: next_open and next_close are always None.
    assert out.next_open is None
    assert out.next_close is None


def test_get_positions(live_server: LiveServer) -> None:
    out = call_tool(live_server, "get_positions")
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert isinstance(out, list)
    # assert_clean_account already verified this list is empty session-wide.
    assert out == []


def test_get_orders(live_server: LiveServer) -> None:
    out = call_tool(live_server, "get_orders")
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert isinstance(out, list)
    assert out == []


def test_get_history(live_server: LiveServer) -> None:
    """Smoke-only: returns a list. Vincent's demo history is unknown."""
    now = datetime.now(timezone.utc)
    one_week_ago = now - timedelta(days=7)
    out = call_tool(
        live_server, "get_history",
        from_ts=one_week_ago.isoformat(),
        to_ts=now.isoformat(),
    )
    assert not (isinstance(out, dict) and "error" in out), f"unexpected error: {out}"
    assert isinstance(out, list)
