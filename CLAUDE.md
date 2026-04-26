# mt5-mcp — Agent Handover Notes

**Status (last updated April 2026):** Phase 2 complete. Tag `phase-2-complete` marks the version with the four mutating tools (`place_order`, `modify_order`, `cancel_order`, `close_position`) and the `PolicyEngine` (preflight + consent + idempotency + audit) shipped on top of Phase 1. 181 passing unit tests. `doctor --smoke-trade` round-trips a place + close against the local MT5. Phase 3 picks up Resources + HTTP transport.

## Where to start

1. **Architecture spec:** `mt5-mcp-architecture.md` (single source of truth for design).
2. **Phase 1 plan:** `docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md` (TDD-style, every step has the actual code).
3. **What's left:** Phase 2 (mutating tools + policy), Phase 3 (resources + HTTP transport), Phase 4 (polish + PyPI release). See architecture §15.

## What Phase 1 shipped

9 read tools (`ping`, `get_terminal_info`, `get_account_info`, `get_quote`, `get_symbols`, `get_market_hours`, `get_positions`, `get_orders`, `get_history`), 2 CLI commands (`doctor`, `export-symbols`), the `MetaTrader5`-wrapping adapter (singleton client + symbol prep + type conversions), config loader with watchdog hot-reload, the FastMCP server bootstrap, and 89 unit tests against a hand-rolled `FakeMT5` (no live terminal needed).

## What Phase 2 added

Four mutating MCP tools (`place_order`, `modify_order`, `cancel_order`, `close_position`), a `PolicyEngine` (`src/mt5_mcp/policy/`) composing four submodules (`preflight.py`, `consent.py`, `idempotency.py`, `audit.py`), SQLite-backed idempotency replay (per-OS path via `platformdirs`), append-only JSONL audit log with size-based rotation, ~85 new unit tests, and `doctor --smoke-trade` for live-terminal verification. Architecture doc §8.* reconciled (HMAC tokens removed in favour of a simple `approval_confirmed` flag; "Soft limits" renamed "Pre-flight limits" with explicit non-security framing).

## Critical patterns Phase 3 MUST follow

These aren't obvious from the architecture doc — they were discovered during Phase 1:

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

## Phase 2 carryover (deferred to Phase 3+)

- **Background TTL sweeper** for idempotency. In-band cleanup is sufficient at expected request volumes; revisit if the DB grows unbounded under heavy load.
- **Audit log compression / archival CLI**. Operators rotate manually; a `mt5-mcp audit prune` command is reasonable Phase 4 polish.
- **`pick_filling_mode` improvements** beyond FOK/IOC/RETURN — broker-specific edge cases may surface during Phase 3 customer onboarding.
- **Multi-leg / OCO / partial-fill orchestration** — explicitly out of scope for v1.

## Test workflow

```bash
pytest -v                              # full suite (~176 tests in ~5s)
pytest tests/test_tools_<x>.py -v      # one tool's tests
pytest -k "history" -v                 # all tests matching "history"
```

Always run the **full** suite before committing — the autouse `_reset_app_context` fixture in `tests/conftest.py` is load-bearing for test isolation, and a slow-burn breakage in one test can propagate.

## Live-terminal smoke check

```bash
python -m mt5_mcp doctor                              # 8x [PASS] expected
python -m mt5_mcp export-symbols --output /tmp/x.csv  # writes a 13-column CSV
python -m mt5_mcp doctor --smoke-trade               # adds a place_order+close_position round-trip
```

If `doctor` reports `[FAIL]` on any tool, that's where Phase 2 starts.

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
