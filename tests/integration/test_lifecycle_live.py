"""Tier 2 lifecycle integration test: place_order + close_position round-trip.

This is the only mutating test in Phase 5. Crank auto_approve_notional in
live_server's config means 0.01-lot trades skip the approval gate (covered
by Phase 2 units exhaustively). Idempotency replay isn't tested live —
also broker-independent and covered by units.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.integration.conftest import LiveServer, call_tool


pytestmark = pytest.mark.integration


def test_lifecycle_market_buy_then_close(
    live_server: LiveServer,
    probe_symbol: str,
    market_open: None,
    opened_tickets: list[int],
) -> None:
    """Place market BUY 0.01 lots, verify in get_positions, close, verify gone, validate audit."""
    place_key = f"phase5-place-{uuid.uuid4()}"
    close_key = f"phase5-close-{uuid.uuid4()}"

    # 1. Place
    place = call_tool(
        live_server, "place_order",
        symbol=probe_symbol, side="buy", type="market",
        volume="0.01", idempotency_key=place_key,
    )
    assert place.get("error") is None, f"place_order failed: {place}"
    assert "ticket" in place and place["ticket"] is not None, \
        f"expected ticket in {place}"
    ticket = place["ticket"]
    opened_tickets.append(ticket)  # cleanup safety net

    # 2. Verify in get_positions
    positions = call_tool(live_server, "get_positions")
    assert not (isinstance(positions, dict) and "error" in positions), \
        f"get_positions failed: {positions}"
    assert any(p.ticket == ticket for p in positions), \
        f"ticket {ticket} not found in {[p.ticket for p in positions]}"

    # 3. Close
    close = call_tool(
        live_server, "close_position",
        ticket=ticket, idempotency_key=close_key,
    )
    assert close.get("error") is None, f"close_position failed: {close}"
    assert close.get("success") is True, f"expected success in {close}"

    # 4. Verify gone
    positions_after = call_tool(live_server, "get_positions")
    assert not (isinstance(positions_after, dict) and "error" in positions_after), \
        f"get_positions failed: {positions_after}"
    assert not any(p.ticket == ticket for p in positions_after), \
        f"ticket {ticket} still open after close"

    # Cleanup-safety no longer needed; remove so teardown skips this ticket.
    opened_tickets.remove(ticket)

    # 5. Validate audit log (sandboxed under tmp_path_factory)
    audit_lines = [
        json.loads(line)
        for line in live_server.audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actions = [(e.get("action"), e.get("symbol")) for e in audit_lines]
    assert ("place_order", probe_symbol) in actions, \
        f"expected place_order/{probe_symbol} in audit; got {actions}"
    assert ("close_position", probe_symbol) in actions, \
        f"expected close_position/{probe_symbol} in audit; got {actions}"
