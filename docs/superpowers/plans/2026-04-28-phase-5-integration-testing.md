# Phase 5 Integration Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-only `tests/integration/` pytest suite that exercises mt5-mcp end-to-end against Vincent's live MT5 demo terminal, gating the deferred v1.0.0 PyPI publish.

**Architecture:** Pure additive test scaffolding — zero production code changes. A new `tests/integration/` package with one shared `conftest.py` (fixtures + `LiveServer` dataclass + `call_tool` helper), a Tier 1 file covering all 9 read tools, and a Tier 2 file with one place_order/close_position lifecycle test. The fixture pre-initialises the MT5 terminal (via env vars `MT5_LOGIN`/`PASSWORD`/`SERVER`) before `build_server`, so `MT5Client.connect()` becomes a no-op-and-true on the already-attached session. Sandbox idempotency DB and audit JSONL under `tmp_path_factory` so tests never pollute the user's real audit log.

**Tech Stack:** pytest 8+, the existing `MetaTrader5` package (live), `mcp[cli]>=1.12`, `pydantic>=2.6`, `platformdirs>=4.0`.

**Spec:** `docs/superpowers/specs/2026-04-28-phase-5-integration-testing-design.md` (commit `493d710`).

**Pre-existing constraints (from CLAUDE.md, must be preserved):**
- Production code MUST NOT import from `tests.` (rule #9)
- Storage paths come from config — never hard-code (rule #8)
- Resources do NOT use `@error_envelope` (not relevant here, no new resources)
- The `_tool_manager.get_tool(name).fn(**kwargs)` private API is the canonical sync test entry point (Phase 1+2 carryover)

**Test invocation conventions:**
- Unit-only: `pytest -v -m "not integration"` — current 243 tests, must stay green
- Integration-only: `pytest -m integration -v` — Phase 5 adds 10 tests here (9 read-tool + 1 lifecycle); existing `tests/test_transport_http_integration.py` contributes 1 more (against `FakeMT5`)
- Collection check (no execution): `pytest --collect-only -m integration -q` — used in tasks below to verify test discovery without needing a live broker

---

## Files this plan touches

```
tests/integration/__init__.py                NEW: marks the integration package
tests/integration/conftest.py                NEW: LiveServer dataclass, fixtures, call_tool helper
tests/integration/test_read_tools_live.py    NEW: 9 Tier 1 tests
tests/integration/test_lifecycle_live.py     NEW: 1 Tier 2 lifecycle test
tests/integration/.env.example               NEW: documents MT5_LOGIN/PASSWORD/SERVER
.gitignore                                   MODIFIED: add `.env`
mt5-mcp-architecture.md                      MODIFIED: §15 lists Phase 5; Phase 4 marked ✅
CLAUDE.md                                    MODIFIED: status header + new "Phase 5 patterns" subsection
README.md                                    MODIFIED: append integration-test section to test-workflow
```

No `src/` changes. No new dependencies in `pyproject.toml`.

---

## Task 1: Integration package skeleton + .env.example + .gitignore + autouse-reset override

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/.env.example`
- Create: `tests/integration/conftest.py`
- Modify: `.gitignore`

This task lays the package foundation. The `conftest.py` for now contains ONLY the autouse-reset override — fixtures and helpers come in Task 2. The override is critical because `tests/conftest.py` has an autouse `_reset_app_context` that wipes the singleton AppContext after every test. Integration tests share a session-scope context built once by `live_server`; if the unit-test reset fires after each integration test, the next test's `get_context()` raises "AppContext not built." A child conftest fixture with the same name overrides the parent.

- [ ] **Step 1: Create the package marker**

```python
# tests/integration/__init__.py
"""Phase 5 integration tests — drive the server end-to-end against a live MT5 demo terminal.

These tests are marked @pytest.mark.integration and excluded from the default
pytest run. Invoke with `pytest -m integration -v`.

Requirements:
- MT5 terminal installed (Windows or Wine).
- Either: terminal already running and logged in to a demo account, OR
  MT5_LOGIN/MT5_PASSWORD/MT5_SERVER env vars set.
- Demo account has zero open positions and zero pending orders before the run.
"""
```

- [ ] **Step 2: Create the env example**

```
# tests/integration/.env.example
# Phase 5 integration tests can launch the MT5 terminal headlessly when
# these are set. Copy this file to `.env` and fill in your demo creds.
# `.env` is gitignored — never commit real credentials.
#
# If any of these is unset, the test fixture falls back to attaching to
# an already-running, already-logged-in MT5 terminal.
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
```

- [ ] **Step 3: Add `.env` to `.gitignore`**

Open `.gitignore` and locate the existing `# Project` block (lines 21-24 today: `symbols.csv`, `tmp_symbols.csv`, `*.jsonl`). Append `.env` directly under that block:

```
# Project
symbols.csv
tmp_symbols.csv
*.jsonl
.env
```

The exact diff is one line added under `*.jsonl`.

- [ ] **Step 4: Create the skeleton conftest with the autouse override**

```python
# tests/integration/conftest.py
"""Fixtures and helpers for the Phase 5 live-broker integration suite.

This conftest overrides the unit-suite's autouse `_reset_app_context` so
the session-scope `live_server` (added in Task 2) can build the AppContext
once and reuse it across the integration session.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_app_context():
    """Override the unit-test autouse reset.

    The parent `tests/conftest.py` wipes the singleton AppContext between
    tests so unit tests can swap their FakeMT5 instances. Integration tests
    share one live MT5 connection across the session and MUST NOT have it
    torn down between tests. Tear-down happens in `live_server` teardown.
    """
    yield
```

- [ ] **Step 5: Verify the unit suite still passes**

Run: `pytest -v -m "not integration"`
Expected: `243 passed` (unchanged from Phase 4).

- [ ] **Step 6: Verify integration collection works (no tests yet)**

Run: `pytest --collect-only -m integration -q`
Expected: lists only the existing `tests/test_transport_http_integration.py::test_http_resources_list_contains_quotes_template` (1 item). No collection errors from the new `tests/integration/` package.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/__init__.py tests/integration/.env.example tests/integration/conftest.py .gitignore
git commit -m "$(cat <<'EOF'
test(phase-5): add integration package skeleton + autouse-reset override

Lays the foundation for live-broker tests:
- tests/integration/ package with __init__.py
- conftest.py with _reset_app_context override (lets session-scope
  live_server share its AppContext across the integration session)
- .env.example documenting MT5_LOGIN/PASSWORD/SERVER
- .gitignore updated to exclude .env

Unit suite unchanged (243 tests still pass).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `LiveServer` dataclass + `live_server` fixture + `call_tool` helper

**Files:**
- Modify: `tests/integration/conftest.py`

The `live_server` fixture builds the FastMCP server with the **real** `MetaTrader5` package. Before `build_server`, it inspects `MT5_LOGIN`/`PASSWORD`/`SERVER` and headlessly initialises the terminal if all three are set. Sandboxes idempotency DB + audit JSONL under `tmp_path_factory`. Sets `auto_approve_notional = 1_000_000` so the lifecycle test's 0.01-lot trade auto-approves. Yields a `LiveServer(server, cfg, audit_path, idem_path)` dataclass.

- [ ] **Step 1: Replace the conftest with the full Task 2 content**

```python
# tests/integration/conftest.py
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
```

- [ ] **Step 2: Verify the unit suite still passes**

Run: `pytest -v -m "not integration"`
Expected: `243 passed`. The new conftest only adds a session-scope fixture and a dataclass; nothing the unit tree imports.

- [ ] **Step 3: Verify integration collection still works**

Run: `pytest --collect-only -m integration -q`
Expected: still 1 item (no new tests added yet). No import errors from `tests/integration/conftest.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "$(cat <<'EOF'
test(phase-5): add LiveServer dataclass, live_server fixture, call_tool helper

Session-scope live_server builds the real FastMCP server against the live
MetaTrader5 package. Headlessly initialises the terminal when MT5_LOGIN,
PASSWORD, SERVER env vars are all set; otherwise attaches to a running
logged-in terminal. Sandboxes idempotency DB + audit JSONL under
tmp_path_factory; cranks auto_approve_notional to 1_000_000 so 0.01-lot
trades skip the approval gate.

call_tool helper invokes tools via the existing
_tool_manager.get_tool(name).fn(**kwargs) sync API.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `probe_symbol` + `market_open` + `assert_clean_account` fixtures

**Files:**
- Modify: `tests/integration/conftest.py`

Three more fixtures: `probe_symbol` picks BTCUSD if available else EURUSD; `market_open` skips a test cleanly if the chosen symbol's last tick is >5 min stale; `assert_clean_account` is autouse session-scope and refuses to start if the demo account has open positions or pending orders.

- [ ] **Step 1: Append to `tests/integration/conftest.py`**

Add the following at the end of the file (after the `live_server` fixture):

```python
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
```

- [ ] **Step 2: Verify the unit suite still passes**

Run: `pytest -v -m "not integration"`
Expected: `243 passed`.

- [ ] **Step 3: Verify integration collection still works**

Run: `pytest --collect-only -m integration -q`
Expected: still 1 item; no import errors.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "$(cat <<'EOF'
test(phase-5): add probe_symbol, market_open, assert_clean_account fixtures

probe_symbol picks BTCUSD if available (24/7), else EURUSD. Edit the
_FALLBACK_SYMBOLS module-level tuple to extend.

market_open is a function-scope fixture that skips a test cleanly when
the probe symbol's last tick is >5 min stale (the only available signal
since get_market_hours returns next_open/next_close as None per v1).

assert_clean_account is session-scope autouse: refuses to start the
suite if the demo account has any open positions or pending orders.
Treats the demo account as a shared resource — won't bulldoze unknown
state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Tier 1 — read tool tests (9 tests in one file)

**Files:**
- Create: `tests/integration/test_read_tools_live.py`

One test per read tool. Each carries `@pytest.mark.integration`. Tests requesting `market_open` skip cleanly when the broker isn't streaming new ticks. Read tools that fail return `{"error": ...}` dicts; success returns Pydantic model instances — assertions handle both shapes.

- [ ] **Step 1: Write the file**

```python
# tests/integration/test_read_tools_live.py
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
```

- [ ] **Step 2: Verify the unit suite still passes**

Run: `pytest -v -m "not integration"`
Expected: `243 passed`. The new test file is integration-marked and excluded.

- [ ] **Step 3: Verify integration collection picks up the 9 new tests**

Run: `pytest --collect-only -m integration -q`
Expected: 10 items total — 1 existing (transport HTTP) + 9 new (`test_ping`, `test_get_terminal_info`, `test_get_account_info`, `test_get_symbols`, `test_get_quote`, `test_get_market_hours`, `test_get_positions`, `test_get_orders`, `test_get_history`). No collection errors.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_read_tools_live.py
git commit -m "$(cat <<'EOF'
test(phase-5): add Tier 1 read-tool live integration tests

Nine tests, one per read tool: ping, get_terminal_info, get_account_info,
get_symbols, get_quote (needs market_open), get_market_hours,
get_positions, get_orders, get_history.

Each validates the live-broker round-trip works on the happy path. The
unit suite covers every error path against FakeMT5; this file only
proves the wire works against a real terminal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `opened_tickets` cleanup-safety fixture

**Files:**
- Modify: `tests/integration/conftest.py`

Function-scope mutable list. Mutating tests append the ticket of any position they place. The fixture's teardown closes anything still in the list with a fresh idempotency key, swallowing errors so cleanup failures don't mask the real test failure. Belt-and-suspenders with the per-test try/finally — both layers exist because a test that raises an unexpected exception between `place_order` and the `try` block still gets cleaned up.

- [ ] **Step 1: Append to `tests/integration/conftest.py`**

Add at the end of the file:

```python
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
```

- [ ] **Step 2: Verify the unit suite still passes**

Run: `pytest -v -m "not integration"`
Expected: `243 passed`.

- [ ] **Step 3: Verify integration collection still works**

Run: `pytest --collect-only -m integration -q`
Expected: still 10 items; no errors.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "$(cat <<'EOF'
test(phase-5): add opened_tickets cleanup-safety fixture

Function-scope mutable list. Mutating tests append ticket numbers; the
teardown closes anything still in the list with a fresh idempotency key,
swallowing errors via warnings so cleanup failures don't mask the real
test failure. Belt-and-suspenders with the in-test try/finally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Tier 2 — lifecycle test (place + close round-trip)

**Files:**
- Create: `tests/integration/test_lifecycle_live.py`

One end-to-end test: place market BUY 0.01 lots, find ticket in `get_positions`, close by ticket, verify it's gone, validate audit log entries. Uses `opened_tickets` for cleanup safety. Each call uses a fresh UUID idempotency key.

- [ ] **Step 1: Write the file**

```python
# tests/integration/test_lifecycle_live.py
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
```

- [ ] **Step 2: Verify the unit suite still passes**

Run: `pytest -v -m "not integration"`
Expected: `243 passed`.

- [ ] **Step 3: Verify integration collection picks up the lifecycle test**

Run: `pytest --collect-only -m integration -q`
Expected: 11 items total — 1 existing transport + 9 read-tool + 1 new lifecycle.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_lifecycle_live.py
git commit -m "$(cat <<'EOF'
test(phase-5): add Tier 2 lifecycle integration test

Single round-trip test: place market BUY 0.01 lots on probe_symbol,
verify ticket appears in get_positions, close by ticket with a fresh
idempotency key, verify ticket is gone, then validate the sandboxed
audit log contains both place_order and close_position entries tagged
with the right symbol.

Cleanup safety via opened_tickets fixture; the in-test path also pops
the ticket on success so teardown is a no-op when the test passes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Architecture doc §15 update

**Files:**
- Modify: `mt5-mcp-architecture.md`

Mark Phase 4 ✅ and add Phase 5 entry. No new top-level section — Phase 5 is testing infrastructure, not a new product surface.

- [ ] **Step 1: Locate §15 in `mt5-mcp-architecture.md`**

The section starts at line 604 (`## 15. What gets built when`). The Phase 4 entry today reads:

```markdown
**Phase 4 — Polish (3 days)**
- `docs/` site auto-generated from docstrings
- Example client configs (Claude Desktop, OpenClaw, Cursor)
- `SECURITY.md` + threat model
- Plugin loader for third-party tools (moved from Phase 3)
- v1.0 release on PyPI
- GitHub repo public + announcement
```

- [ ] **Step 2: Replace the Phase 4 block and append Phase 5**

```markdown
**Phase 4 — Polish (3 days)** ✅ complete
- Public README, SECURITY.md, CHANGELOG.md, example client configs (Claude Desktop, Cursor)
- GitHub Actions test CI on Windows runners (Python 3.10/3.11/3.12)
- v1.0.0 packaged and tagged (publish to PyPI gated on Phase 5)
- Plugin loader and auto-generated docs site deferred to v1.1+

**Phase 5 — Integration testing against demo terminal (1-2 days)**
- `tests/integration/` suite covering 9 read tools + one place_order/close_position lifecycle against a real broker
- Local pytest only; no CI integration
- Gates the deferred v1.0.0 push to GitHub and PyPI publish
- See `docs/superpowers/specs/2026-04-28-phase-5-integration-testing-design.md`
```

The "Total: ~3 weeks" line below stays as-is.

- [ ] **Step 3: Verify rendering**

Open `mt5-mcp-architecture.md` (or skim with `head -650 mt5-mcp-architecture.md | tail -50`) and verify the §15 block reads cleanly with both Phase 4 marked ✅ and Phase 5 listed.

- [ ] **Step 4: Commit**

```bash
git add mt5-mcp-architecture.md
git commit -m "$(cat <<'EOF'
docs(phase-5): mark Phase 4 ✅ and add Phase 5 to architecture §15

Architecture doc didn't list Phase 5 (it ended at Phase 4). Added a
short entry pointing at the design spec; updated Phase 4 to reflect
what actually shipped (no docs site, no plugin loader; both deferred).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: CLAUDE.md status header + Phase 5 patterns subsection + Phase 4 carryover

**Files:**
- Modify: `CLAUDE.md`

Three edits:
- (a) Status header changes from "Phase 4 complete" to "Phase 5 complete".
- (b) New "Phase 5 patterns all future integration tests MUST follow" subsection (items 19–23) inserted after the existing "Phase 3 patterns" section and before "Phase 3 carryover".
- (c) One line added to "Phase 4 carryover" about deferred production-side headless launch.

- [ ] **Step 1: Replace the status header**

Find the line at the top of `CLAUDE.md`:

```markdown
**Status (last updated April 2026):** Phase 4 complete — `mt5-mcp` v1.0.0 shipped to PyPI. Tag `phase-3-complete` marks the previous milestone. Phase 4 added the public README, `SECURITY.md`, `CHANGELOG.md`, example MCP client configs (Claude Desktop stdio + HTTP, Cursor), GitHub Actions test CI, and the `1.0.0` PyPI release. 243 passing unit tests (unchanged from Phase 3). Phase 5 (automated integration tests against a real MT5 demo) is queued.
```

Replace with:

```markdown
**Status (last updated April 2026):** Phase 5 complete — `tests/integration/` suite ships with 9 read-tool live tests + 1 place_order/close_position lifecycle test against a real MT5 demo terminal. Phase 4 v1.0.0 packaging is unchanged; Phase 5 added zero production code (purely test scaffolding + docs). 243 passing unit tests + 11 integration tests (10 live-broker + 1 transport HTTP). PyPI publish of v1.0.0 unblocked: `git push` + `uv publish` next.
```

- [ ] **Step 2: Insert the Phase 5 patterns subsection**

Find the existing section heading `## Phase 3 carryover` in CLAUDE.md. Immediately ABOVE that line, insert the following block:

```markdown
## Phase 5 patterns all future integration tests MUST follow

These were discovered during Phase 5 implementation and apply to any future
test that touches a real MT5 terminal.

### 19. Sandbox idempotency DB and audit JSONL under tmp_path

Same rule as unit tests (#8 above). An integration test that writes to the
user's real `~/.local/share/mt5-mcp/audit.jsonl` is a defect — the audit log
is the operator's record of intentional trading, not a test scratchpad.
The `live_server` fixture in `tests/integration/conftest.py` is the canonical
example: it writes a per-session config under `tmp_path_factory.mktemp(...)`
with `[idempotency] path` and `[audit] path` redirected.

### 20. Refuse to bulldoze unknown account state

The `assert_clean_account` autouse fixture probes `get_positions` and
`get_orders` once per session and refuses to start if either is non-empty.
Future integration tests MUST NOT bypass this fixture. If a test legitimately
needs an open position to start (e.g., testing modify_order), it should open
the position itself in the test body and clean up via `opened_tickets`.

### 21. BTCUSD primary, EURUSD fallback, market_open as a backstop

The `probe_symbol` fixture picks BTCUSD when available so tests don't depend
on the day of the week. EURUSD is the fallback for brokers without crypto.
The `market_open` fixture skips market-state-dependent tests when the
selected symbol's last tick is >5 min stale. Tests that don't need a fresh
quote (`account_info`, `terminal_info`, `get_symbols`, etc.) MUST NOT request
this fixture — it adds an unnecessary call and skip path.

### 22. Crank auto_approve_notional in test config; never test approval gate live

The consent gate is pure local logic. Re-validating it against a real broker
costs trades and adds zero information beyond what Phase 2 unit tests cover.
Set `[policy] auto_approve_notional = "1000000"` in the test config and let
0.01-lot trades route through the unguarded path.

### 23. No production code changes from integration tests

Headless launch of the MT5 terminal is achieved by the fixture calling
`mt5.initialize(login=..., password=..., server=...)` BEFORE `build_server()`.
The subsequent `MT5Client.connect()` calls `mt5.initialize()` (no args) which
mt5lib treats as a no-op-and-true on an already-initialised session. Do not
add `login/password/server` to production config or `MT5Client` to support
test fixtures — the production contract is "the operator launches and
authenticates the terminal."

## Phase 5 carryover

- **Tier 3 expansion** (`modify_order`, `cancel_order`, error-path tests) deferred to a future phase if customer reports surface broker-specific bugs.
- **Approval-flow live integration** deferred — consent gate is pure local logic and Phase 2 unit tests are exhaustive.
- **GitHub Actions integration** deferred — self-hosted Windows runner with creds in GH secrets is heavy infrastructure for a solo project.
- **Production-side headless terminal launch** deferred — Phase 5 fixtures pre-init the terminal directly. If a future user asks for systemd / NSSM service deployments, add `[mt5] login/password/server` config fields and wire them through `MT5Client.connect()`.

```

- [ ] **Step 3: Add a single carryover line to the existing "Phase 4 carryover" section**

In the existing `## Phase 4 carryover (deferred to Phase 5+ or to ad-hoc fixes)` section, append a new bullet to the existing list (just before the line that says "All Phase 2/3 carryovers..." or at the end of the bullet list, whichever is clearer):

```markdown
- **Headless terminal launch in production config** — Phase 5 fixtures achieve this via direct `mt5.initialize(login=...)` before `build_server`. If a future user asks for production-side headless launch (e.g., for systemd / NSSM service deployments), add `[mt5] login/password/server` config fields and wire them through `MT5Client.connect()`. Out of scope for v1.0.
```

- [ ] **Step 4: Verify the unit suite still passes (sanity)**

Run: `pytest -v -m "not integration"`
Expected: `243 passed`. CLAUDE.md edits don't touch code, but worth one cycle to be sure nothing regressed across the recent set of edits.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(phase-5): update CLAUDE.md status, add Phase 5 patterns subsection

- Status header reflects Phase 5 ship + 11 integration tests + zero
  production code changes.
- New "Phase 5 patterns" subsection (items 19-23): sandbox idem/audit
  under tmp_path, refuse to bulldoze account state, BTCUSD primary +
  EURUSD fallback + market_open backstop, crank auto_approve_notional
  for tests, no production code changes from tests.
- New "Phase 5 carryover" subsection lists deferred Tier 3 expansion,
  live approval-flow tests, CI integration, production headless launch.
- Phase 4 carryover gains one line about deferred production headless
  launch (the one item Phase 5 made concrete via test fixtures).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: README integration-test subsection

**Files:**
- Modify: `README.md`

Append a short "Integration tests against a live MT5 demo" subsection inside the existing test-workflow section.

- [ ] **Step 1: Locate the test-workflow section in `README.md`**

Search for the existing testing instructions — typically a heading like `## Testing` or `## Development` that documents `pytest` invocation. Insert the new subsection inside or immediately after it (matching the existing heading depth — if the parent is `##`, use `###` for the new subsection).

- [ ] **Step 2: Append the subsection**

```markdown
### Integration tests against a live MT5 demo

The `tests/integration/` suite drives the server end-to-end against a real
MT5 terminal. Requirements:

1. MT5 terminal installed (Windows or Wine on Linux).
2. Either: terminal already running and logged in to a demo account, OR
   `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` env vars set so the fixture
   can launch the terminal headlessly. See `tests/integration/.env.example`.
3. Demo account starts with zero open positions and zero pending orders.
   The suite refuses to start otherwise — close any orphans manually first.

Run with:

    pytest -m integration -v

The lifecycle test places one micro-lot (0.01) order on BTCUSD (or EURUSD
fallback) and closes it. Use a demo account, not a live one.
```

If the README has no existing test section, add this directly under a top-level `## Testing` heading near the bottom of the README (before any "License" section).

- [ ] **Step 3: Verify rendering**

Open `README.md` and confirm the new subsection sits under the right parent heading and reads cleanly.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(phase-5): document `pytest -m integration` invocation in README

Adds a short subsection to the test-workflow section explaining the
prerequisites (running terminal or env-var creds; clean demo account)
and the canonical invocation. Single micro-lot trade per run on BTCUSD
or EURUSD fallback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Live end-to-end validation (Vincent runs)

**Files:** none (manual validation step).

This is the acceptance gate. Vincent runs the suite against his demo terminal. The implementing agent CANNOT do this — it has no broker access. Mark this task `pending` and wait for Vincent's confirmation.

- [ ] **Step 1: Verify the demo account starts clean**

Open the MT5 terminal. Confirm the "Trade" tab shows zero open positions and zero pending orders. Close any leftovers from prior testing.

- [ ] **Step 2: Run the integration suite (first pass)**

```bash
pytest -m integration -v
```

Expected: 11 items collected. All pass (or `test_get_quote` and `test_lifecycle_market_buy_then_close` skip cleanly with "market closed" if the BTCUSD fallback to EURUSD applies AND the FX market is closed — should be rare given BTCUSD is 24/7).

- [ ] **Step 3: Verify the demo account is still clean**

Re-check the MT5 "Trade" tab. Should be exactly the same state as Step 1 (zero open, zero pending). The lifecycle test placed one order and closed it; if anything is still open, `opened_tickets` cleanup didn't fire — investigate before re-running.

- [ ] **Step 4: Run the integration suite a second time (idempotency proof)**

```bash
pytest -m integration -v
```

Expected: same all-green outcome. Two consecutive runs from a clean account both pass — proves the suite is idempotent against itself (no leftover audit-DB state, no leftover positions).

- [ ] **Step 5: Verify the unit suite still passes**

```bash
pytest -v -m "not integration"
```

Expected: `243 passed` (no regressions from the Phase 5 docs/conftest edits).

- [ ] **Step 6: Tag and proceed with the deferred Phase 4 release ops**

If Steps 1-5 all pass, Phase 5 is shippable. Vincent then runs the Phase 4 release ops that were deferred:

```bash
git push -u origin main           # CI runs against the Phase 5 commits
git push origin v1.0.0            # tag push triggers any tag-gated workflow
uv build && uv publish            # PyPI upload (needs UV_PUBLISH_TOKEN)
pip install mt5-mcp -U            # smoke in fresh venv
python -m mt5_mcp doctor          # final live check
```

If any Phase 5 test surfaces a v1.0 bug, bump to v1.0.1 (or v1.1.0 for API-breaking changes) before any of the above. The current `v1.0.0` tag can be deleted-and-recreated only if `origin` has not yet received it.

---

## Self-review

**1. Spec coverage:**

| Spec section | Plan task |
|---|---|
| §3 file layout — `tests/integration/__init__.py` | Task 1 |
| §3 file layout — `tests/integration/conftest.py` | Tasks 1, 2, 3, 5 (incremental) |
| §3 file layout — `test_read_tools_live.py` | Task 4 |
| §3 file layout — `test_lifecycle_live.py` | Task 6 |
| §3 file layout — `.env.example` | Task 1 |
| §3 file layout — `.gitignore` | Task 1 |
| §3 file layout — architecture doc | Task 7 |
| §3 file layout — CLAUDE.md | Task 8 |
| §3 file layout — README.md | Task 9 |
| §4.1 `live_server` fixture (incl. headless launch) | Task 2 |
| §4.2 `probe_symbol` fixture | Task 3 |
| §4.3 `market_open` fixture | Task 3 |
| §4.4 `assert_clean_account` fixture | Task 3 |
| §4.5 `opened_tickets` fixture | Task 5 |
| §5.1 9 Tier 1 read-tool tests | Task 4 |
| §5.2 lifecycle test | Task 6 |
| §6 approval-flow bypass via `auto_approve_notional` | Task 2 (in `live_server` config) |
| §7 idempotency-key handling | Tasks 5, 6 (UUID per call) |
| §8 demo-terminal connection (env + attach + .env.example) | Tasks 1, 2 |
| §9 architecture + CLAUDE.md updates | Tasks 7, 8 |
| §10 README update | Task 9 |
| §11 acceptance criteria | Task 10 |
| §13 risks (autouse-reset override addresses session-context risk) | Task 1 |

All spec sections covered.

**2. Placeholder scan:** No "TBD"/"TODO"/"add appropriate error handling" anywhere. Each step has the exact code or exact command. The two doc tasks (8, 9) reference existing CLAUDE.md/README.md sections by heading text rather than line number because those line numbers will shift across the chain of commits — heading text is the stable anchor.

**3. Type consistency:**
- `LiveServer` dataclass defined once in Task 2; consumed by name in Tasks 3, 4, 5, 6.
- `call_tool(live, name, **kwargs)` signature defined once in Task 2; consumed by name in Tasks 3, 4, 5, 6.
- `_FALLBACK_SYMBOLS` constant defined once in Task 3; referenced in CLAUDE.md item 21.
- Fixture names (`live_server`, `probe_symbol`, `market_open`, `assert_clean_account`, `opened_tickets`) consistent across all tasks and the CLAUDE.md patterns.
- `auto_approve_notional = "1000000"` — string literal in TOML, parsed to `Decimal` per existing config schema (`src/mt5_mcp/config.py:42`). Matches the test pattern at `tests/test_tools_place_order.py:106`.

No inconsistencies.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-phase-5-integration-testing.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, two-stage review (spec compliance + code quality) per task, fast iteration. This is the same flow that delivered Phases 2, 3, and 4.

**2. Inline Execution** — Execute tasks in this session via `superpowers:executing-plans`, batch with checkpoints.

Which approach?
