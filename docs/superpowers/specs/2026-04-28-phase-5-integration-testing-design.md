# Phase 5 — Integration Testing Against the MT5 Demo

**Status:** Design approved 2026-04-28. Awaits implementation plan (`writing-plans`).
**Owner:** Vincent
**Phase 4 commit:** `a33a384` (`v1.0.0` tag, local only — `git push` and `uv publish` deferred until Phase 5 closes successfully)
**Architecture spec:** `mt5-mcp-architecture.md` §15 (phase order; Phase 5 not yet listed — this design adds it)

---

## 1. Goal

Add a local-only integration test suite that exercises `mt5-mcp` end-to-end against Vincent's MT5 demo terminal. The suite catches broker-specific behavior the `FakeMT5` cannot model: real adapter conversions, real `terminal_info().time` shape in the wild, real audit/idempotency under live latency, and a real `place_order → close_position` round-trip through the policy engine.

Phase 5 closes when:

1. `pytest -m integration` from the repo root runs the new suite against a live demo terminal and produces an all-green summary (or a clean SKIPPED with a clear reason if the market is closed and the broker doesn't offer a 24/7 instrument).
2. The suite refuses to start if the demo account has any open positions or pending orders, with an explicit "manual cleanup required" error.
3. The Tier 2 lifecycle test places exactly one micro-lot order, closes it, and leaves the demo account in the same state it started in.
4. The 243-test unit suite (`pytest -v -m "not integration"`) still passes — no regressions.
5. Architecture doc §15 is updated to list Phase 5 and reflect Phase 4 as ✅ shipped.
6. CLAUDE.md is updated with a "Phase 5 patterns" subsection so future contributors don't accidentally pollute the real audit log or DB when adding integration tests.

This is a single-tag delivery: `v1.0.0` (no version bump — Phase 5 ships no production code that affects published behavior; it is purely test scaffolding plus documentation). Once Phase 5 is green, the deferred Phase 4 release ops resume: `git push origin main && git push origin v1.0.0 && uv publish`.

---

## 2. Foundation decisions (locked during brainstorm)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Local-only suite. No CI integration.** Tests live in the repo, marked `@pytest.mark.integration`, run by Vincent on his workstation. GitHub Actions never executes them. | A self-hosted Windows runner with MT5 + demo creds in GitHub secrets is heavy infrastructure for a solo project. The "did Phase 5 pass?" gate is on Vincent's honour for v1.0; CI integration can come in v1.1+ as a separate ticket if needed. |
| 2 | **Coverage tier: read-only + one round-trip mutating.** All 9 read tools each get one test. `place_order → close_position` lifecycle gets exactly one combined test. `modify_order`, `cancel_order`, and error-path tests deferred. | The policy engine is the most novel surface shipped; one round-trip on a real broker is enough to validate idempotency, audit, approval bypass, and adapter all at once. Tier 3 expansion adds flakiness surface (broker rejections for non-bug reasons) without proportional information. |
| 3 | **Per-test cleanup + assert clean precondition.** Session-scope autouse fixture probes `get_positions`/`get_orders`; if non-empty, suite errors before touching anything. Mutating tests track tickets in a per-test list whose teardown closes whatever is still open. | Treats the demo account as a shared resource (Vincent might be using it manually). Refuses to bulldoze unknown state. The "manual cleanup required" message is friction at the right time — orphan positions deserve human eyes before automation does more. |
| 4 | **BTCUSD as primary symbol; EURUSD as secondary.** Fixture probes `get_symbols`, picks `BTCUSD` if available (24/7 trading), falls back to `EURUSD` (FX, 24/5). Market-state-dependent tests use `market_open` fixture that skips cleanly on weekends/holidays only when fallback applies. | 24/7 instruments make "did Phase 5 pass?" independent of what day Vincent runs it. EURUSD remains the explicit fallback so the suite still ships value on brokers that don't list crypto. |
| 5 | **Bypass approval flow via high `auto_approve_notional`.** Test config sets `auto_approve_notional = 1_000_000` so 0.01-lot trades auto-approve. The consent gate's two-call retry path is NOT validated against the live broker. | Consent gate is pure local logic; Phase 2 unit tests (`tests/test_policy_consent.py`) cover it exhaustively. Re-validating it against a real broker adds zero information and consumes a test slot. |
| 6 | **Sandbox audit + idempotency under `tmp_path`.** Test config writes `[idempotency] path` and `[audit] path` into pytest's temporary directory. The user's real `~/.local/share/mt5-mcp/` (or `%LOCALAPPDATA%\mt5-mcp\`) is never touched. | Same rule as unit tests (CLAUDE.md item 8). An integration test polluting the user's real audit log is a defect — the audit log is the operator's record of intentional trading, not a test scratchpad. |
| 7 | **Demo creds via env vars, with attach-fallback.** Fixture reads `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` from environment. If all three are set → headless headed launch. If any unset → attach to already-running, already-logged-in terminal (current `doctor` behavior). `tests/integration/.env.example` committed; `.env` gitignored. | Env vars are the standard secret pattern: compose with any shell, never get committed, no extra dependency (no python-dotenv). The fallback preserves Vincent's existing workflow with `doctor` and lets contributors who don't want headless launch keep using their interactive terminal. |
| 8 | **No production code changes.** Headless launch is achieved by the fixture calling `mt5.initialize(login=..., password=..., server=...)` BEFORE `build_server()`. The subsequent `MT5Client.connect()` calls `mt5.initialize()` (no args), which mt5lib treats as a no-op-and-returns-true on an already-initialised session. `MT5Client.__init__` and `connect()` are unchanged. | Keeps Phase 5 a purely additive testing phase. Adding `login/password/server` to production config + `MT5Client` would be product surface area that other deployments (stdio, HTTP) would inherit by accident. The current contract — "the operator launches and authenticates the terminal" — is the right one for a local-first MCP. |
| 9 | **Architecture doc gets §15 update only; no new section.** Phase 5 is testing infrastructure, not a new product surface. A new §19 would mirror what the spec already covers and rot. | The architecture doc describes what the server does, not how it's tested. CLAUDE.md is the right home for "patterns future phases must preserve" learnings. |

---

## 3. File layout

All paths relative to repo root. **No `src/` changes.**

```
tests/integration/__init__.py                NEW: marks the integration package
tests/integration/conftest.py                NEW: live_server, probe_symbol, market_open,
                                                  assert_clean_account, opened_tickets
tests/integration/test_read_tools_live.py    NEW: Tier 1 — 9 tests, one per read tool
tests/integration/test_lifecycle_live.py     NEW: Tier 2 — 1 lifecycle test
tests/integration/.env.example               NEW: documents MT5_LOGIN/PASSWORD/SERVER
.gitignore                                   MODIFIED: add .env exclusion
mt5-mcp-architecture.md                      MODIFIED: §15 lists Phase 5; Phase 4 marked ✅
CLAUDE.md                                    MODIFIED: status header to "Phase 5 complete";
                                                       new "Phase 5 patterns" subsection
README.md                                    MODIFIED: tiny test-workflow paragraph for
                                                       `pytest -m integration` invocation
```

The existing `tests/test_transport_http_integration.py` stays where it is — it's a transport smoke that runs against `FakeMT5`, not a broker integration test, despite carrying the same `@pytest.mark.integration` marker. The marker meaning broadens to "any test that needs an external resource" (an HTTP server thread or a live MT5 terminal). This is fine: marker semantics stay consistent (`pytest -m integration` runs both; default unit run excludes both).

The integration package is a **separate directory** (`tests/integration/`) rather than mixed into `tests/`. Reasons: (1) the `conftest.py` semantics differ from the unit suite (no `_reset_app_context` autouse, no `FakeMT5` injection), so isolating them in a sub-package prevents collisions; (2) directory makes `pytest tests/integration/` an obvious "run everything live" command; (3) future contributors immediately see the boundary between hermetic and live tests.

---

## 4. Fixtures (`tests/integration/conftest.py`)

### 4.1 `live_server` (session-scope)

Builds the FastMCP server with the **real** `MetaTrader5` package (passes `mt5_module=None`). Writes a sandboxed `config.toml` into `tmp_path_factory.mktemp("phase5")` with:

- `[idempotency] path = "<tmp>/idem.db"`
- `[audit] path = "<tmp>/audit.jsonl"`
- `[policy] auto_approve_notional = 1_000_000` (auto-approve 0.01-lot trades)
- No `[mt5] terminal_path` (attach to running terminal)

Before calling `build_server`, the fixture inspects environment for `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER`. If all three present, calls `mt5.initialize(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)` directly so the terminal launches and authenticates. Then calls `build_server(...)`; the inner `MT5Client.connect()` re-calls `mt5.initialize()` (no args) which mt5lib short-circuits to true on an already-initialised session.

The fixture yields a small dataclass `LiveServer(server: FastMCP, cfg: Config, audit_path: Path, idem_path: Path)` so tests can both drive the server (via `server._tool_manager.get_tool(...).fn(...)`) and read the sandboxed audit log directly. Teardown runs `reset_context_for_tests()`. The terminal is left running for the next session (matches Vincent's workflow with `doctor`).

If `mt5.initialize(...)` fails (bad creds, server unreachable), the fixture re-raises with a clear message: "Phase 5 integration: MT5 initialise failed with login=<masked>. Check MT5_LOGIN/PASSWORD/SERVER env vars or start the terminal manually and unset them."

### 4.2 `probe_symbol` (session-scope, depends on `live_server`)

Calls `get_symbols`. Returns `"BTCUSD"` if present in the broker's symbol list, otherwise `"EURUSD"`. If neither is present, raises with: `"Phase 5: broker offers neither BTCUSD nor EURUSD; suite cannot proceed. Add the symbol you want to test against to tests/integration/conftest.py::_FALLBACK_SYMBOLS."` (Hardcoded list of probes is a one-line constant in the file.)

### 4.3 `market_open` (function-scope, depends on `live_server` and `probe_symbol`)

For tests that need a live market. Calls the `get_market_hours` tool for the probe symbol; if the broker reports the symbol as currently closed, the fixture calls `pytest.skip(f"market closed for {probe_symbol}")`. Tests that don't depend on market state (`ping`, `get_terminal_info`, `get_account_info`, `get_symbols`, `get_market_hours` itself, `get_history`) don't request this fixture.

Note: the `get_market_hours` tool returns `next_open`/`next_close` as `None` per v1 contract (CLAUDE.md item 4 of Phase 1+2 carryover). The fixture infers "open" by calling `get_quote(probe_symbol)` and checking the returned tick's `time` is within the last 5 minutes — stale tick = market closed. This is a heuristic but the only one available without `sessions_quotes` parsing.

### 4.4 `assert_clean_account` (session-scope, autouse for the integration package, depends on `live_server`)

Runs once before any integration test. Pulls the `live_server` fixture (so the server is built and connected), then calls `get_positions` and `get_orders` via `call_tool`. If either returns a non-empty list, raises:

```
RuntimeError: Phase 5 precondition failed: demo account has <N> open positions and
<M> pending orders. Manual cleanup required before running integration tests.
Open positions: [ticket=..., symbol=..., volume=...] ...
Pending orders: [ticket=..., symbol=..., type=...] ...
```

Suite refuses to start. Vincent closes the orphans in the MT5 terminal manually and re-runs.

### 4.5 `opened_tickets` (function-scope)

A mutable list. Mutating tests append the ticket of any position they place. Fixture teardown iterates the list and calls `close_position(ticket)` for each one with a fresh idempotency key, swallowing errors (best-effort cleanup; errors are logged via warnings.warn so the test still reports its real outcome).

This is belt-and-suspenders with the per-test `try/finally` — both layers exist because a test that raises an unexpected exception between `place_order` and the `try` block still gets cleaned up.

---

## 5. Test list

### 5.1 `test_read_tools_live.py` — Tier 1 (9 tests)

| Test | Asserts | Fixtures |
|---|---|---|
| `test_ping` | `result["ok"] is True`; `result["latency_ms"] >= 0` | `live_server` |
| `test_terminal_info` | `result["connected"] is True`; `result["build"]` is a positive int | `live_server` |
| `test_account_info` | `Decimal(result["balance"]) > 0`; `result["currency"]` is non-empty 3+ char str; `result["leverage"] >= 1` | `live_server` |
| `test_get_symbols` | returns ≥1 symbol; probe symbol is in the result | `live_server`, `probe_symbol` |
| `test_get_quote` | `Decimal(result["bid"]) > 0`; `Decimal(result["ask"]) >= Decimal(result["bid"])`; tick `time` is aware UTC and within last 5 min | `live_server`, `probe_symbol`, `market_open` |
| `test_get_market_hours` | structurally complete; `next_open is None` and `next_close is None` per v1 contract | `live_server`, `probe_symbol` |
| `test_get_positions` | returns a list (will be `[]` due to clean precondition) | `live_server` |
| `test_get_orders` | returns a list (will be `[]` due to clean precondition) | `live_server` |
| `test_get_history` | accepts `from_datetime=datetime(now-7d, tzinfo=UTC)`; returns a list | `live_server` |

`test_get_history` does NOT assert any specific deals — Vincent's demo account history is unknown. It only proves the call shape works against real data.

### 5.2 `test_lifecycle_live.py` — Tier 2 (1 test)

`test_lifecycle_market_buy_then_close`:

```python
def test_lifecycle_market_buy_then_close(live_server, probe_symbol, market_open,
                                          opened_tickets, tmp_path):
    """Round-trip: place market BUY 0.01 lots, find it in get_positions,
    close by ticket, verify it's gone, validate audit log entries.
    """
    place_key = f"phase5-place-{uuid.uuid4()}"
    close_key = f"phase5-close-{uuid.uuid4()}"

    # 1. Place
    place = call_tool(live_server, "place_order",
                      symbol=probe_symbol, side="buy", type="market",
                      volume="0.01", idempotency_key=place_key)
    assert place.get("error") is None, f"place_order failed: {place}"
    assert "ticket" in place, f"expected ticket in {place}"
    ticket = place["ticket"]
    opened_tickets.append(ticket)  # cleanup safety net

    # 2. Verify in get_positions
    positions = call_tool(live_server, "get_positions")
    assert any(p["ticket"] == ticket for p in positions), \
        f"ticket {ticket} not found in {positions}"

    # 3. Close
    close = call_tool(live_server, "close_position",
                      ticket=ticket, idempotency_key=close_key)
    assert close.get("error") is None, f"close_position failed: {close}"
    assert close.get("success") is True, f"expected success in {close}"

    # 4. Verify gone
    positions_after = call_tool(live_server, "get_positions")
    assert not any(p["ticket"] == ticket for p in positions_after), \
        f"ticket {ticket} still open after close"

    opened_tickets.remove(ticket)  # cleanup no longer needed

    # 5. Validate audit log
    audit_lines = [json.loads(line)
                   for line in live_server.audit_path.read_text().splitlines()]
    actions = [(e["action"], e["symbol"]) for e in audit_lines]
    assert ("place_order", probe_symbol) in actions
    assert ("close_position", probe_symbol) in actions
```

The `call_tool` helper (defined in `conftest.py`) calls `live_server.server._tool_manager.get_tool(name).fn(**kwargs)` — same pattern unit tests use today (see CLAUDE.md "Phase 1 + Phase 2 carryover" note about this private API still being live). When FastMCP ships a public sync tool accessor, both unit and integration tests migrate together.

---

## 6. Approval-flow handling

The test config sets `auto_approve_notional = 1_000_000`. A 0.01-lot BTCUSD trade at ~$60k spot price is ~$600 notional, well under threshold. The policy engine routes through the `requires_approval=False` path in `place_order`, returns `{ticket, ...}` directly, no preview, no second-call retry. This is the same path `doctor --smoke-trade` exercises today.

The two-call approval-confirmed retry path is **not** tested live. Reasons:

1. The consent gate is pure local logic; the policy engine never contacts the broker during `requires_approval=True` first-pass (it returns the preview before any broker call). Phase 2 unit tests in `tests/test_policy_consent.py` and `tests/test_tools_place_order.py` cover the gate exhaustively across happy path, identical-fields validation, bait-and-switch detection, expiry, single-use semantics, and idempotency interaction.
2. Re-validating it against a real broker adds two extra trades per run (one per gated tool call) for zero net information.
3. If a future Phase 6 wants to validate the gate end-to-end, a single dedicated test can crank `auto_approve_notional` to a low value and exercise the two-call dance. Out of scope for v1.0.

---

## 7. Idempotency-key handling

Each test generates a fresh key via `f"phase5-{action}-{uuid.uuid4()}"`. The integration suite never tests the "send the same key twice, get the cached result" path against a live broker. Reasons mirror §6: idempotency cache hit semantics are broker-independent and Phase 2 unit tests (`tests/test_policy_idempotency.py`) cover them exhaustively.

The idempotency DB is sandboxed under `tmp_path_factory` per session, so even if the same key were re-used by accident, it wouldn't collide with the user's real DB or persist across runs.

---

## 8. Demo terminal connection

### 8.1 Env-var path (recommended)

```bash
# Vincent sets these in his shell once (or in a .env consumed by his shell):
export MT5_LOGIN=12345678
export MT5_PASSWORD='his demo password'
export MT5_SERVER='Broker-Demo'

# Then runs:
pytest -m integration -v
```

The fixture sees all three set and calls:

```python
ok = mt5.initialize(
    login=int(os.environ["MT5_LOGIN"]),
    password=os.environ["MT5_PASSWORD"],
    server=os.environ["MT5_SERVER"],
)
```

Terminal launches if not running, logs in to demo, fixture proceeds.

### 8.2 Attach-fallback path

If any of the three env vars is unset, the fixture skips the explicit `initialize(...)` call. `MT5Client.connect()` then runs `mt5.initialize()` with no args, which attaches to whatever terminal session is currently running (must be logged in to demo). This matches the workflow Vincent uses for `doctor` today.

If no terminal is running and no env vars are set, `mt5.initialize()` returns `False` and the existing `MT5Client.connect()` raises `MT5Error` with code `CONNECTION_FAILED`. The integration suite surfaces this as an ERROR (not a SKIP) — the test environment is fundamentally not set up.

### 8.3 `tests/integration/.env.example`

```
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

The `.env` file itself is not parsed by the suite — env vars must be exported into the shell. The `.env.example` is documentation only. (Avoiding python-dotenv keeps Phase 5 dependency-free; if Vincent wants `.env` auto-loading, he can use any shell-level loader of his choice.)

### 8.4 `.gitignore` update

Add a single line:

```
.env
```

(In addition to the existing entries.) Any `.env` file anywhere in the repo is now untracked.

---

## 9. Architecture doc & CLAUDE.md updates

### 9.1 `mt5-mcp-architecture.md` §15

Replace:

```
**Phase 4 — Polish (3 days)**
- ...
- v1.0 release on PyPI
- GitHub repo public + announcement
```

With:

```
**Phase 4 — Polish (3 days)** ✅ complete
- Public README, SECURITY.md, CHANGELOG.md, example client configs
- GitHub Actions test CI on Windows runners (Python 3.10/3.11/3.12)
- v1.0.0 packaged and tagged (publish to PyPI gated on Phase 5)
- Plugin loader and docs site deferred to v1.1+

**Phase 5 — Integration testing against demo terminal (1-2 days)**
- `tests/integration/` suite covering 9 read tools + one place_order/close_position
  lifecycle against a real broker
- Local pytest only; no CI integration
- Gates the deferred v1.0.0 push to GitHub and PyPI publish
- See `docs/superpowers/specs/2026-04-28-phase-5-integration-testing-design.md`
```

`§16 ("Open questions")` is unchanged. No new top-level section.

### 9.2 `CLAUDE.md`

Two updates:

**(a) Status header** changes from "Phase 4 complete — `mt5-mcp` v1.0.0 shipped to PyPI" to:

```
**Status (last updated April 2026):** Phase 5 complete — integration test suite
ships with one-tier read coverage and a Tier 2 round-trip lifecycle. Phase 4
v1.0.0 packaging is unchanged; Phase 5 added zero production code. PyPI publish
of v1.0.0 unblocked: `git push` + `uv publish` next.
```

**(b) New subsection** after "Phase 3 carryover" and before "Phase 4 carryover":

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
quote (account_info, terminal_info, get_symbols, etc.) MUST NOT request
this fixture — it adds an unnecessary call and skip path.

### 22. Crank auto_approve_notional in test config; never test approval gate live

The consent gate is pure local logic. Re-validating it against a real broker
costs trades and adds zero information beyond what Phase 2 unit tests cover.
Set `[policy] auto_approve_notional = 1_000_000` in the test config and let
0.01-lot trades route through the unguarded path.

### 23. No production code changes from integration tests

Headless launch of the MT5 terminal is achieved by the fixture calling
`mt5.initialize(login=..., password=..., server=...)` BEFORE `build_server()`.
The subsequent `MT5Client.connect()` calls `mt5.initialize()` (no args) which
mt5lib treats as a no-op-and-true on an already-initialised session. Do not
add `login/password/server` to production config or `MT5Client` to support
test fixtures — the production contract is "the operator launches and
authenticates the terminal."
```

The "Phase 4 carryover" section adds one item:

```
- **Headless terminal launch in production config** — Phase 5 fixtures
  achieve this via direct `mt5.initialize(login=...)` before `build_server`.
  If a future user asks for production-side headless launch (e.g., for
  systemd / NSSM service deployments), add `[mt5] login/password/server`
  config fields and wire them through `MT5Client.connect()`. Out of scope
  for v1.0.
```

---

## 10. README update

Append to the existing test-workflow section (`## Test workflow` or equivalent):

```markdown
### Integration tests against a live MT5 demo

The `tests/integration/` suite drives the server end-to-end against a real
MT5 terminal. Requirements:

1. MT5 terminal installed (Windows or via Wine on Linux).
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

---

## 11. Acceptance criteria

Phase 5 is shippable when ALL of the following are true:

1. `pytest -v -m "not integration"` passes (243/243 unit tests, no regressions).
2. `pytest -m integration -v` against Vincent's demo terminal produces an all-green summary with at least 9 tests run (Tier 1 read tools, all passing) and 1 lifecycle test passing (when market is open) or 1 lifecycle test skipped (when fallback to EURUSD and market is closed). With BTCUSD as primary, "skipped" should be rare.
3. The demo account has the same number of open positions and pending orders after `pytest -m integration` as before (zero, modulo the precondition).
4. `tests/integration/.env.example` is committed; `.env` is in `.gitignore`; no real credentials anywhere in the repo.
5. `mt5-mcp-architecture.md` §15 lists Phase 5 and marks Phase 4 ✅.
6. `CLAUDE.md` status header is updated; "Phase 5 patterns" subsection (items 19–23) added.
7. `README.md` has the new "Integration tests" subsection.
8. Two consecutive runs of `pytest -m integration` from a clean account both pass — proves the suite is idempotent against itself.

After Phase 5 is green, Vincent runs the deferred Phase 4 release ops:

```bash
git push -u origin main           # CI runs
git push origin v1.0.0            # tag push
uv build && uv publish            # PyPI upload
pip install mt5-mcp -U            # smoke in fresh venv
python -m mt5_mcp doctor          # final live check
```

---

## 12. Out of scope (deferred to later phases or ad-hoc)

| Item | Why deferred | When to revisit |
|---|---|---|
| Tier 3: `modify_order`, `cancel_order`, error-path tests (invalid volume, market closed rejections, invalid symbol) | Adds flakiness surface (broker rejections for non-bug reasons) without proportional information. Phase 2 unit tests cover the local logic. | If a customer reports a Phase 2 modify/cancel bug, write a regression test then. |
| Approval-flow live integration | Consent gate is pure local logic; unit tests are exhaustive. | Phase 6 if a customer reports approval semantics not matching docs. |
| GitHub Actions CI integration | Self-hosted Windows runner with creds in GH secrets is heavy infrastructure for solo project. | When project grows past one engineer or a customer asks for CI proof. |
| Auto-launching MT5 terminal in production | Out of scope for v1.0. Operators launch/auth manually today; fixture-only headless launch is sufficient for tests. | When asked for systemd / NSSM service deployments. |
| Streaming/HTTP integration over the live broker | Phase 3's existing `tests/test_transport_http_integration.py` (against `FakeMT5`) is the transport smoke. Real-broker streaming integration adds wallclock-dependent assertions (tick rates, P&L noise) without unique coverage. | If a customer reports streaming bugs that look broker-specific. |
| Multi-broker validation | Vincent's demo broker is the only target. | When other broker users contribute tests against their accounts. |
| `python-dotenv` for `.env` auto-loading | Adds a runtime dependency for one developer convenience. | Never — shell-level loaders solve this without a Python dep. |
| Stress / load testing (rapid-fire orders, subscription fanout under N clients) | Not a v1.0 product claim. | If observed regressions in production deployments. |

All Phase 1/2/3/4 carryovers (idempotency TTL sweeper, audit prune CLI, `pick_filling_mode` improvements, non-loopback HTTP bind, per-subscriber backpressure, dead-subscriber TTL sweeper, test migration off `_tool_manager.get_tool().fn`, plugin loader, docs site, trusted-publishing OIDC) remain deferred. Phase 5 adds none and clears none.

---

## 13. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| BTCUSD not available on Vincent's broker → suite always falls back to EURUSD → weekend runs always skip the lifecycle test | Medium | Documented in spec §4.2. The `_FALLBACK_SYMBOLS` constant in `conftest.py` is a one-line edit if a third 24/7 instrument is needed. |
| Test crashes between `place_order` and the `try` block → orphan position on demo account | Low (the `opened_tickets` fixture has its own teardown that catches this) | Belt-and-suspenders via `opened_tickets` + `try/finally`. If both fail, the next session's `assert_clean_account` blocks with the orphan info — Vincent sees the problem immediately. |
| `mt5.initialize(login=..., password=..., server=...)` fails because of stale terminal session, then headless launch tries to start a second terminal and conflicts | Low | The fixture catches `initialize()` returning False and re-raises with a clear message naming the env vars. Vincent restarts the terminal. |
| Real-broker latency makes the 5-min staleness threshold in `market_open` flaky for thinly-traded symbols (less likely on BTCUSD/EURUSD) | Low | 5-min threshold is generous. If it ever flakes, raise to 10 min. |
| Integration test pollutes user's audit log because someone adds a future test that forgets the `live_server` fixture | Low | CLAUDE.md item 19 documents this rule. Code review enforces. |
| Demo broker imposes a per-day order limit that the lifecycle test exhausts | Low | Lifecycle test places exactly 1 order per run. Vincent runs the suite manually, not on a schedule. |
| `mt5.initialize()` no-op-and-true assumption on already-initialised session is wrong on some MT5 builds → fixture's headless `initialize` plus `MT5Client.connect()`'s `initialize()` causes a double-init failure | Low (mt5lib documents this idempotent behavior) | If observed, the fixture can set `_initialised = True` on the `MT5Client` instance after the headless init, bypassing `connect()` entirely. Track as a Phase 5 patch if it surfaces. |

---

## 14. Open questions (resolved during brainstorm)

| Q | Decision |
|---|---|
| Where do tests run? | Local-only. No CI. (decision #1) |
| What coverage scope? | Tier 1 + Tier 2 only. (decision #2) |
| How to handle account state between runs? | Per-test cleanup + assert clean precondition. (decision #3) |
| What when market is closed? | BTCUSD primary so it usually doesn't matter; EURUSD fallback skips cleanly. (decision #4) |
| How to bypass approval flow? | Crank `auto_approve_notional`. (decision #5) |
| Where do creds come from? | Env vars with attach-fallback. (decision #7) |
| Any production code changes? | No. Fixture pre-inits the terminal. (decision #8) |
| Architecture doc surface? | §15 entry; no new section. (decision #9) |

---

## 15. Implementation handoff

This spec hands to the `writing-plans` skill, which will produce a step-by-step plan in `docs/superpowers/plans/2026-04-28-phase-5-integration-testing.md`. The plan will sequence:

1. `tests/integration/__init__.py` + skeleton `conftest.py` with the `assert_clean_account` precondition (smallest verifiable slice).
2. `live_server` + `probe_symbol` + `market_open` fixtures.
3. `tests/integration/test_read_tools_live.py` — all 9 Tier 1 tests.
4. `opened_tickets` fixture + `tests/integration/test_lifecycle_live.py`.
5. `tests/integration/.env.example` + `.gitignore` update.
6. Architecture doc §15 update.
7. CLAUDE.md status + Phase 5 patterns subsection.
8. README integration-test subsection.
9. End-to-end smoke: clean account → `pytest -m integration -v` → all green → rerun → still green.

After the plan is approved, the implementing session uses the standard subagent-driven dual-review flow (implementer + spec-review + code-quality-review per task) — same workflow that delivered Phases 2–4.

---

*End of Phase 5 design. Hand to writing-plans for implementation plan, then to subagent-driven-development for execution.*
