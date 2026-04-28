"""Fixtures and helpers for the Phase 5 live-broker integration suite.

This conftest overrides the unit-suite's autouse `_reset_app_context` so
the session-scope `live_server` can build the AppContext once and reuse
it across the integration session.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mt5_mcp.config import Config, load_config
from mt5_mcp.server import build_server, reset_context_for_tests


@pytest.fixture(autouse=True)
def _reset_app_context():
    """Override the unit-test autouse reset.

    The parent `tests/conftest.py` wipes the singleton AppContext between
    tests so unit tests can swap their FakeMT5 instances. Integration tests
    share one live MT5 connection across the session and MUST NOT have it
    torn down between tests. Tear-down happens in `live_server` teardown.
    """
    yield


@dataclass
class LiveServer:
    """Bundle yielded by the `live_server` fixture."""
    server: Any  # FastMCP — typed as Any to avoid an import for one annotation
    cfg: Config
    audit_path: Path
    idem_path: Path


def call_tool(live: LiveServer, name: str, **kwargs: Any) -> Any:
    """Invoke an MCP tool by name; return whatever the tool returns.

    Read tools return Pydantic model instances on success and a
    {"error": ...} dict on failure. Mutating tools always return a dict
    (containing either {ticket, success, ...} or {error: ...} or
    {request_id, summary, ...} for an approval preview). Test code is
    expected to check the actual shape returned by each tool — don't
    normalise here, the asymmetry is intentional in the production code.
    """
    return live.server._tool_manager.get_tool(name).fn(**kwargs)


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> LiveServer:
    """Build the FastMCP server against the real MetaTrader5 package.

    If MT5_LOGIN, MT5_PASSWORD, MT5_SERVER are all set in the environment,
    the fixture headlessly initialises the terminal first. Otherwise it
    falls back to attaching to a running, logged-in terminal.

    See `tests/integration/.env.example` for the env var template.

    Sandboxes idempotency DB + audit JSONL under tmp_path_factory so the
    user's real audit log is never touched. Cranks auto_approve_notional
    so 0.01-lot trades skip the approval gate (covered by Phase 2 units).
    """
    reset_context_for_tests()

    tmp = tmp_path_factory.mktemp("phase5")
    audit_path = tmp / "audit.jsonl"
    idem_path = tmp / "idem.db"
    cfg_path = tmp / "config.toml"
    cfg_path.write_text(
        '[policy]\n'
        'auto_approve_notional = "1000000"\n\n'
        f'[idempotency]\npath = "{idem_path.as_posix()}"\n\n'
        f'[audit]\npath = "{audit_path.as_posix()}"\n',
        encoding="utf-8",
    )

    # Headless launch when all three creds are set; else attach-fallback.
    login = os.environ.get("MT5_LOGIN")
    password = os.environ.get("MT5_PASSWORD")
    server = os.environ.get("MT5_SERVER")
    if login and password and server:
        try:
            import MetaTrader5 as mt5  # type: ignore[import]
        except ImportError:
            pytest.skip("MetaTrader5 package not importable — Phase 5 needs Windows + MT5")

        ok = mt5.initialize(login=int(login), password=password, server=server)
        if not ok:
            pytest.fail(
                "Phase 5 integration: mt5.initialize(login=<masked>, server=%r) "
                "returned False. Check MT5_LOGIN/PASSWORD/SERVER env vars or "
                "start the terminal manually and unset them." % server
            )

    fastmcp_server = build_server(mt5_module=None, config_path=cfg_path)
    cfg = load_config(cfg_path)

    yield LiveServer(
        server=fastmcp_server,
        cfg=cfg,
        audit_path=audit_path,
        idem_path=idem_path,
    )

    reset_context_for_tests()


_FALLBACK_SYMBOLS: tuple[str, ...] = ("BTCUSD", "EURUSD")
"""Symbols probed by `probe_symbol` in priority order. BTCUSD is 24/7;
EURUSD is the FX fallback. Edit this constant to add more brokers' symbols."""


@pytest.fixture(scope="session")
def probe_symbol(live_server: LiveServer) -> str:
    """Pick the first available symbol from _FALLBACK_SYMBOLS.

    Raises if none are present on the broker — Phase 5 needs at least one
    of BTCUSD or EURUSD (or whatever Vincent adds to the constant).
    """
    symbols = call_tool(live_server, "get_symbols")
    if isinstance(symbols, dict) and "error" in symbols:
        pytest.fail(f"Phase 5: get_symbols failed: {symbols['error']}")
    available = {s.name for s in symbols}
    for candidate in _FALLBACK_SYMBOLS:
        if candidate in available:
            return candidate
    pytest.fail(
        f"Phase 5: broker offers none of {_FALLBACK_SYMBOLS}; suite cannot proceed. "
        f"Add the symbol you want to test against to "
        f"tests/integration/conftest.py::_FALLBACK_SYMBOLS."
    )


@pytest.fixture
def market_open(live_server: LiveServer, probe_symbol: str) -> None:
    """Skip the calling test cleanly if the probe symbol's market is closed.

    Heuristic: call get_quote and check the returned tick's `time` is
    within the last 5 minutes. A stale tick means the market is closed
    (the broker isn't streaming new ticks). This is the only signal
    available because `get_market_hours` returns `next_open`/`next_close`
    as None per v1 contract.
    """
    from datetime import datetime, timedelta, timezone

    quote = call_tool(live_server, "get_quote", symbol=probe_symbol)
    if isinstance(quote, dict) and "error" in quote:
        pytest.skip(f"market closed for {probe_symbol}: {quote['error']['code']}")
    age = datetime.now(timezone.utc) - quote.time
    if age > timedelta(minutes=5):
        pytest.skip(
            f"market closed for {probe_symbol}: last tick {age.total_seconds():.0f}s old"
        )


@pytest.fixture(scope="session", autouse=True)
def assert_clean_account(live_server: LiveServer) -> None:
    """Refuse to start the suite if the demo account has open state.

    Probes get_positions and get_orders once per session. Any non-empty
    list aborts the run with a clear "manual cleanup required" message.
    Treats the demo account as a shared resource (Vincent might be using
    it manually too) — refuses to bulldoze unknown state.
    """
    positions = call_tool(live_server, "get_positions")
    if isinstance(positions, dict) and "error" in positions:
        pytest.fail(f"Phase 5 precondition: get_positions failed: {positions['error']}")
    orders = call_tool(live_server, "get_orders")
    if isinstance(orders, dict) and "error" in orders:
        pytest.fail(f"Phase 5 precondition: get_orders failed: {orders['error']}")

    if positions or orders:
        pos_summary = ", ".join(
            f"ticket={p.ticket} symbol={p.symbol} volume={p.volume}" for p in positions
        ) or "none"
        ord_summary = ", ".join(
            f"ticket={o.ticket} symbol={o.symbol} type={o.type}" for o in orders
        ) or "none"
        pytest.fail(
            f"Phase 5 precondition failed: demo account has {len(positions)} open "
            f"positions and {len(orders)} pending orders. Manual cleanup required "
            f"before running integration tests.\n"
            f"  Open positions: {pos_summary}\n"
            f"  Pending orders: {ord_summary}"
        )


@pytest.fixture
def opened_tickets(live_server: LiveServer) -> list[int]:
    """Cleanup-safety net for mutating tests.

    A test that places a position appends its ticket to this list. The
    teardown closes any ticket still in the list (best-effort, errors
    are warned not raised, so a failed cleanup never masks the real
    test failure).

    Tests SHOULD also wrap their place_order call in try/finally and
    pop the ticket once it's been closed normally — this fixture is
    the safety net for the unexpected-exception case.
    """
    import uuid
    import warnings

    tickets: list[int] = []
    yield tickets

    for ticket in tickets:
        try:
            out = call_tool(
                live_server, "close_position",
                ticket=ticket,
                idempotency_key=f"phase5-cleanup-{uuid.uuid4()}",
            )
            if out.get("error") is not None or not out.get("success"):
                warnings.warn(
                    f"Phase 5 cleanup: close_position(ticket={ticket}) failed: {out}"
                )
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"Phase 5 cleanup: ticket={ticket} exception {exc!r}")
