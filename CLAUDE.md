# mt5-mcp — Agent Handover Notes

**Status (last updated April 2026):** Phase 5 complete — `tests/integration/` suite ships with 9 read-tool live tests + 1 place_order/close_position lifecycle test against a real MT5 demo terminal. Phase 4 v1.0.0 packaging is unchanged; Phase 5 added zero production code (purely test scaffolding + docs). 243 passing unit tests + 11 integration tests (10 live-broker + 1 transport HTTP). PyPI publish of v1.0.0 unblocked: `git push` + `uv publish` next.

## Where to start

1. **Architecture spec:** `mt5-mcp-architecture.md` (single source of truth for design).
2. **Phase 1 plan:** `docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md` (TDD-style, every step has the actual code).
3. **What's next:** Phase 5 (automated integration tests against a real MT5 demo). Spec to be written; user has demo account access. Architecture §15 currently ends at Phase 4 — Phase 5 will require an architecture-doc update.

## What Phase 1 shipped

9 read tools (`ping`, `get_terminal_info`, `get_account_info`, `get_quote`, `get_symbols`, `get_market_hours`, `get_positions`, `get_orders`, `get_history`), 2 CLI commands (`doctor`, `export-symbols`), the `MetaTrader5`-wrapping adapter (singleton client + symbol prep + type conversions), config loader with watchdog hot-reload, the FastMCP server bootstrap, and 89 unit tests against a hand-rolled `FakeMT5` (no live terminal needed).

## What Phase 2 added

Four mutating MCP tools (`place_order`, `modify_order`, `cancel_order`, `close_position`), a `PolicyEngine` (`src/mt5_mcp/policy/`) composing four submodules (`preflight.py`, `consent.py`, `idempotency.py`, `audit.py`), SQLite-backed idempotency replay (per-OS path via `platformdirs`), append-only JSONL audit log with size-based rotation, ~85 new unit tests, and `doctor --smoke-trade` for live-terminal verification. Architecture doc §8.* reconciled (HMAC tokens removed in favour of a simple `approval_confirmed` flag; "Soft limits" renamed "Pre-flight limits" with explicit non-security framing).

## What Phase 3 added

Three MCP resources (`account://current`, `positions://current`, `quotes://{symbol}`), all readable and subscribable. A shared streaming subsystem (`src/mt5_mcp/streaming/`) with a `Poller` daemon thread and a `Dispatcher` for per-URI change-fanout. Change-detection excludes floating P&L by design (see architecture §17). HTTP transport (`serve --transport http`), loopback-only, with optional bearer-token auth (`transport.http.auth_token`). A `FastMCPSubscriber` adapter bridges the Poller daemon thread to the FastMCP asyncio event loop via `asyncio.run_coroutine_threadsafe`. `doctor` gained a `[streaming]` check. Test helper `tests/_resource_helpers.py::read_resource(server, uri)` is the canonical way to drive resource handlers from tests. ~62 new unit tests (243 total). Architecture doc §17 and §18 added.

## What Phase 4 added

No production code changes — this was a packaging and docs phase. Bumped `pyproject.toml` to `1.0.0`, re-authored to "Vincent" with a personal security contact, added `[project.urls]`. Rewrote `README.md` for first-time PyPI users (with a Windows VPS deployment section covering both agent-on-VPS stdio and agent-local-via-SSH-tunnel HTTP patterns). Added `SECURITY.md`, `CHANGELOG.md`, three example client configs (`examples/clients/`), and a single GitHub Actions test workflow on Windows runners across Python 3.10/3.11/3.12. Tagged `v1.0.0` and published to PyPI. Repo moved from `Fintrix-Markets/mt5-trading-mcp` to `vincentwongso/mt5-mcp`.

## Critical patterns all future phases MUST follow

These aren't obvious from the architecture doc — they were discovered during Phases 1–3:

### 1. `error_envelope` decorator: tool body must call `get_context()` itself

FastMCP's Pydantic-based tool-schema generator can't JSON-schemafy `AppContext.client: MT5Client`. So the planned `def my_tool(ctx: AppContext, ...) -> X:` pattern **does not work**. Use:

```python
@mcp.tool()
@error_envelope
def my_tool(arg: str) -> SomeType:
    """Docstring."""
    ctx = get_context()  # FIRST line, always
    # ... use ctx.client, ctx.symbols, ctx.config
```

The decorator (in `src/mt5_mcp/tools/_common.py`) catches both `MT5Error` (using its carried `ErrorDetail`) and any other `Exception` (wrapping as `INTERNAL_ERROR` via `errors.internal_error`); the full traceback is logged server-side so a Python stack never escapes to the MCP client. Read tools are wrapped; `ping` is deliberately NOT wrapped (it must work pre-connect).

### 2. `terminal_not_connected_error()` factory — use it, don't inline `ErrorDetail(code="TERMINAL_NOT_CONNECTED", ...)`

Lives in `src/mt5_mcp/errors.py`. Both the adapter and read tools use it. When Phase 2 mutating tools detect a connection drop, use the same factory. Same shape applies to `internal_error(exc)` (for unexpected exceptions inside a tool body).

### 2b. Route mt5lib data calls through `ctx.client.call(...)`

The reinit-aware wrapper is the canonical access pattern:

```python
raws = ctx.client.call(lambda m: m.positions_get(symbol=symbol))
```

This makes the architecture's "transparent reinit on mid-session NOT_INITIALIZED" guarantee real. Direct `ctx.client.mt5.<method>(...)` access is only acceptable for **constants** (`m.ORDER_FILLING_IOC`, `m.SYMBOL_FILLING_FOK`, etc.) and `ping` (which intentionally bypasses retry to detect connection state).

### 3. UTC-portable test timestamps

When a test needs an epoch, write `int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())` — never naive `.timestamp()`. Naive `.timestamp()` is interpreted as local time and breaks tests on non-UTC dev machines.

### 4. `infer_broker_tz_offset` AttributeError fallback

Some real-world MT5 builds omit `terminal_info().time`. `MT5Client.connect()` catches `AttributeError` and falls back to `broker_offset_minutes=0` with a warning. Regression test: `tests/test_adapter_mt5_client.py::test_connect_falls_back_when_terminal_info_lacks_time`. If Phase 2 changes connect-time behaviour, preserve this fallback.

### 5. Timestamps: aware UTC ONLY, enforced at the type system

The Pydantic `_Base` validator (`src/mt5_mcp/types.py`) rejects naive datetimes AND non-UTC offsets. The adapter's `epoch_to_utc(epoch, broker_offset_minutes)` is the single producer. Don't add another timestamp source — every datetime that ends up in a tool output must pass through `adapter/conversions.py`.

### 6. Test fakes, not `MagicMock`

`tests/fakes.py` has hand-rolled dataclasses for every MT5 type we touch. Phase 2 tests should extend `FakeMT5` (e.g. add `_order_send` slot for `place_order`) rather than reach for `unittest.mock.MagicMock`. The strong typing makes "missing test data" fail loudly.

### 7. Mutating tools route through `ctx.policy.guard(...)`

Every mutating tool body computes `requires_approval` itself (gate logic varies by action — notional for place/close, SL-widening for modify, never for cancel) and passes the boolean to the engine. The engine handles the retry mechanism, idempotency, and audit; the tool body is just adapter prep + `with ctx.policy.guard(...)` + `g.execute(...)` + `g.finalize(...)`.

```python
with ctx.policy.guard(
    "place_order", req,
    requires_approval=notional >= cfg.policy.auto_approve_notional,
    preview_factory=build_preview if requires_approval else None,
    preflight_inputs=PreflightInputs(notional=notional),
    current_price=ref_price if approval_confirmed else None,
    symbol_point=Decimal(str(info.point)) if approval_confirmed else None,
) as g:
    if g.short_circuit is not None:
        return g.short_circuit
    g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
    return g.finalize(order_result_from_mt5_response, request_echo=...,
                       action="place_order", symbol=symbol,
                       request_volume=req.volume)
```

The engine's stage order matters: idempotency → confirmed-consent → preflight → first-pass-consent → execute. Confirmed-consent runs BEFORE preflight so a bait-and-switch surfaces as `INVALID_APPROVAL`, not `EXCEEDS_LOCAL_LIMIT`.

### 8. Storage paths come from config — never hard-code

Idempotency DB and audit JSONL paths default to `platformdirs.user_data_dir("mt5-mcp", appauthor=False)`. The `appauthor=False` is critical: without it, Windows produces a double `mt5-mcp\mt5-mcp\` segment. Tests MUST pass `config_path=tmp_path/"config.toml"` to `build_server(...)` to redirect both files into a sandboxed location — otherwise the tests pollute `~/.local/share/mt5-mcp/` (or `%LOCALAPPDATA%\mt5-mcp\`).

### 9. Production code MUST NOT import from `tests.`

A copy-paste hazard surfaced during Phase 2 (Tasks 6 and 14): tool implementations briefly imported MT5 constants like `POSITION_TYPE_BUY` from `tests.fakes` because the constant names matched. The fix is always `ctx.client.mt5.POSITION_TYPE_BUY` — the live module exposes the same constants, and `FakeMT5` mirrors them as instance fields.

### 10. `request_hash` excludes `approval_*` fields

Idempotency hashes the canonical JSON of the request EXCLUDING `approval_confirmed` and `approval_request_id`. This makes "send the same trade twice with the same idempotency key" return the cached result, regardless of whether the second call carried an approval token. Don't change this without thinking through retry semantics.

### 11. ApprovalStore is in-memory and single-use

Pending approval previews live in `ApprovalStore` (in-memory dict), keyed by ULID. They expire after `policy.approval_ttl_seconds` (default 300s). A process restart legitimately invalidates pending approvals — the human should re-confirm against the current state of the world. Single-use: `pop()` removes the entry whether the retry succeeds or fails.

### 12. `validate_retry` does NOT check `action`

Identical-fields validation in `policy/consent.py::validate_retry` covers `symbol`, `side`, `type`, `volume`, `ticket` — but NOT `action`. The engine dispatches by `action` at the call site, so a retry can only ever reach `validate_retry` under the same action that issued the preview. Don't move action-validation into `validate_retry` — it's the engine's responsibility.

## Phase 1 + Phase 2 carryover

All five Phase 1 final-review items closed before Phase 2 started:

- ✅ **`MT5Client.call(fn)`** is the public reinit-aware wrapper; every read tool and `SymbolPrep` route mt5lib data calls through it. Constants and `ping` skip it.
- ✅ **Decimals serialise via `Annotated[Decimal, PlainSerializer(...)]`** (`_DecimalStr` alias in `types.py`). `model_config.json_encoders` is gone; deprecation warnings dropped from 29 → 0.
- ✅ **`error_envelope` catches `Exception`** (not just `MT5Error`) and emits the new `INTERNAL_ERROR` envelope (`errors.internal_error`). The full traceback logs server-side; only the exception class name reaches the client.
- ✅ **`get_market_hours` docstring** explicitly states `next_open`/`next_close` are always `None` in v1 — `sessions_quotes` parsing is deferred to a future release.
- ✅ **`_RES_IPC_TIMEOUT` removed** from `mt5_client.py`. Phase 2 will re-introduce it with a backing test if IPC-timeout retries become necessary.

Still deferred: the 9 test files using `server._tool_manager.get_tool(name).fn` private API. FastMCP has not shipped a public sync accessor yet — migrate when it lands.

## Phase 2 carryover

- **Background TTL sweeper** for idempotency. In-band cleanup is sufficient at expected request volumes; revisit if the DB grows unbounded under heavy load.
- **Audit log compression / archival CLI**. Operators rotate manually; a `mt5-mcp audit prune` command is reasonable Phase 4 polish.
- **`pick_filling_mode` improvements** beyond FOK/IOC/RETURN — broker-specific edge cases may surface during Phase 4 customer onboarding.
- **Multi-leg / OCO / partial-fill orchestration** — explicitly out of scope for v1.

## Phase 3 patterns all future phases MUST preserve

These were discovered during Phase 3 implementation and are not obvious from the architecture doc.

### 13. Resources do NOT use `@error_envelope`

The `@error_envelope` decorator is tools-only. Resources raise `MT5Error(...)` directly; FastMCP catches it and renders the MCP-protocol `error` response. Do not wrap resource handlers with `@error_envelope`.

### 14. `mcp.settings.host/port` mutation, not `run()` kwargs

FastMCP 3.x's `mcp.run()` does not accept `host` or `port` keyword arguments for the `streamable-http` transport. The transport module sets them on `mcp.settings` before calling `run()`:

```python
mcp.settings.host = resolved_host
mcp.settings.port = cfg.transport.http.port
mcp.run(transport="streamable-http")
```

If a future FastMCP version changes this, `src/mt5_mcp/transport.py` is the single place to update.

### 15. Subscribe hooks via `mcp._mcp_server.subscribe_resource()`

FastMCP does not expose resource subscribe/unsubscribe hooks at its high-level surface. Use the low-level `Server` underneath:

```python
mcp._mcp_server.subscribe_resource(uri_str, on_subscribe)
mcp._mcp_server.unsubscribe_resource(uri_str, on_unsubscribe)
```

`FastMCPSubscriber` (`src/mt5_mcp/server.py`) wraps this. The subscribe callback bridges the Poller daemon thread to the asyncio event loop via `asyncio.run_coroutine_threadsafe`. Do not call the asyncio session methods directly from the Poller thread.

### 16. `Poller.poll_once()` calls `dispatcher.reap_dead_subscribers()` each cycle

This is the only mechanism that removes subscriptions from dead HTTP sessions. There is no separate sweeper. HTTP-session-detached subscriptions are reaped on the next dispatch attempt after their callback raises. This is acceptable at current load; see Phase 3 carryover for the known gap.

### 17. Streaming snapshot dataclasses live in `streaming/snapshots.py`

`src/mt5_mcp/streaming/snapshots.py` holds the frozen dataclasses used as snapshot tokens for change-detection. These are production code. `tests/fakes.py` does NOT export snapshot types. Production code MUST NOT import from `tests.`.

### 18. Test helper `tests/_resource_helpers.py::read_resource(server, uri)`

This is the canonical way to drive a resource handler through FastMCP from a test. Do not duplicate the helper per test file. See `tests/test_resources_*.py` for usage patterns.

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

## Phase 3 carryover

- **Plugin loader for third-party tools** — was in Phase 3 spec; moved to Phase 4, then deferred again to v1.1+ during Phase 4 scoping. No stub or scaffolding exists yet.
- **HTTP transport non-loopback bind** — currently raises `ConfigError` at startup if a non-loopback host is configured. Phase 4 if a customer asks for LAN-accessible deployment.
- **Per-subscriber backpressure / outbox queues** — current sequential fanout is fine for local-first with few subscribers. Revisit if observed lag under multiple concurrent HTTP sessions.
- **Background TTL sweeper for HTTP-session-detached subscriptions** — `reap_dead_subscribers` runs on poll cycles, so subscriptions that never see a fanout (during long quiet periods on stable markets) may not reap promptly. Acceptable today; revisit if it becomes load-bearing.

## Phase 4 carryover (deferred to Phase 5+ or to ad-hoc fixes)

All items below were explicitly out of scope for v1.0; revisit as customer reports come in or as part of Phase 5 if integration tests surface them:

- **Auto-generated docs site** (was on the original Phase 4 list; deferred to v1.1+).
- **Plugin loader for third-party tools** — no stub or scaffolding yet; deferred to v1.1+.
- **Trusted Publishing GitHub Actions workflow** — manual `uv publish` worked for `1.0.0`; wire OIDC publishing if releases get frequent.
- **Headless terminal launch in production config** — Phase 5 fixtures achieve this via direct `mt5.initialize(login=...)` before `build_server`. If a future user asks for production-side headless launch (e.g., for systemd / NSSM service deployments), add `[mt5] login/password/server` config fields and wire them through `MT5Client.connect()`. Out of scope for v1.0.
- **All Phase 2/3 carryovers** still deferred (idempotency TTL sweeper, audit prune CLI, `pick_filling_mode` improvements, non-loopback HTTP bind, per-subscriber backpressure, dead-subscriber TTL sweeper, test migration off `_tool_manager.get_tool().fn`).
- **`LICENCE` → `LICENSE` rename** — non-blocking; can roll into a future doc-only commit.
- **`CONTRIBUTING.md`** — non-blocking; add when the first external contribution lands.

## Test workflow

```bash
pytest -v                              # full suite (243 tests)
pytest -v -m "not integration"         # unit tests only (no live terminal needed)
pytest tests/test_tools_<x>.py -v      # one tool's tests
pytest -k "history" -v                 # all tests matching "history"
```

Always run the **full** suite before committing — the autouse `_reset_app_context` fixture in `tests/conftest.py` is load-bearing for test isolation, and a slow-burn breakage in one test can propagate.

## Live-terminal smoke check

```bash
python -m mt5_mcp doctor                              # 9x [PASS] expected (includes [streaming])
python -m mt5_mcp export-symbols --output /tmp/x.csv  # writes a 13-column CSV
python -m mt5_mcp doctor --smoke-trade               # adds a place_order+close_position round-trip
python -m mt5_mcp serve --transport http             # start HTTP server (loopback, port 8765)
```

If `doctor` reports `[FAIL]` on any check, that's where investigation starts.

## Memory

User memories for this project live at `~/.claude/projects/C--projects-mt5-trading-mcp/memory/`. Notable entries:

- `feedback_subagent_model.md` — use sonnet (not haiku) for general-purpose subagents.
- `project_fastmcp_envelope_pattern.md` — the no-`ctx`-parameter rule (above).
- `project_terminal_info_time_quirk.md` — the AttributeError fallback (above).

## Don't surprise the user

- This project is **broker-agnostic**. No hardcoded broker URLs / server names / symbol conventions. Fintrix is the launch reference user, not an embedded constraint.
- This project is **local-first**. No cloud component, no telemetry by default, no auto-update. The MCP runs on the customer's machine in the same process tree as their agent runtime.
- The MCP is **not the security boundary** — the broker's MT5 server enforces hard limits. Pre-flight checks in the policy engine (Phase 2) are UX guardrails, not security controls.

---

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (90-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk vitest run          # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->
