# Phase 2 — Mutating Tools and Policy Engine

**Status:** Design approved 2026-04-26. Awaits implementation plan (`writing-plans`).
**Owner:** Vincent
**Phase 1 commit:** `2fe9265` (carryover items closed)
**Architecture spec:** `mt5-mcp-architecture.md` §5 (mutating tools), §6 (types), §7 (config), §8 (policy engine)

---

## 1. Goal

Ship the four mutating MCP tools (`place_order`, `modify_order`, `cancel_order`, `close_position`) on top of a single policy engine that handles pre-flight limits, consent gating, idempotency, and audit logging. Phase 2 closes when all four tools are tested end-to-end against `FakeMT5._order_send` AND a real-terminal smoke check (`doctor` extended to cover one round-trip place + close in demo mode) is green.

This is a single-tag delivery: `phase-2-complete`. No partial release.

---

## 2. Foundation decisions (locked during brainstorm)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Consent gate uses a simple `approval_confirmed: true` flag**, not HMAC-signed tokens. Trust boundary is the transport (stdio process boundary or Tailscale node identity in Phase 3). MCP validates retry matches preview within tolerance. | HMAC adds key-management ceremony without meaningful security: if either side is compromised, tokens forge. Transport authentication is where real authn lives. |
| 2 | **All four mutating tools land together** in v0.2 (single `phase-2-complete` tag). | The policy framework is 70% of the work; once paid, the four tools are thin wrappers. Splitting saves no time. |
| 3 | **Hybrid integration pattern**: keep `@error_envelope` decorator (Phase 1); fold preflight + consent + idempotency + audit into a single `ctx.policy.guard(...)` context-manager call inside each tool body. | Decorator stack would have to thread shared state (request, preview, idempotency key, timing) — ugly. A single engine call keeps the tool body inspectable and the engine independently testable. |
| 4 | **`platformdirs` for default storage paths**, both overridable in `config.toml`. SQLite for idempotency, JSONL for audit. | Native feel on Windows / macOS / Linux. SQLite for idempotency because crash-mid-trade is exactly when dedupe must survive a restart. JSONL audit so `Get-Content -Wait` / `tail -f` works. |

---

## 3. File layout

```
src/mt5_mcp/
├── adapter/
│   ├── conversions.py          (existing) — add order_request_to_mt5_dict,
│   │                                          order_result_from_mt5_response
│   ├── mt5_client.py           (existing) — no change
│   └── symbols.py              (existing) — already has validate_volume +
│                                              quantise_price + pick_filling_mode
├── policy/                     (NEW package)
│   ├── __init__.py             — exports PolicyEngine
│   ├── engine.py               — class PolicyEngine, the ctx.policy.guard(...) entry point
│   ├── preflight.py            — check_preflight_limits(action, request, account, config)
│   ├── consent.py              — ApprovalRequest store (in-memory), build_preview,
│   │                              validate_retry, ULID generation
│   ├── idempotency.py          — IdempotencyStore (SQLite-backed)
│   └── audit.py                — AuditLog (JSONL append-only with size-based rotation)
├── tools/
│   ├── orders.py               (existing) — add place_order, modify_order, cancel_order
│   ├── positions.py            (existing) — add close_position
│   └── _common.py              (existing) — no change to error_envelope
├── types.py                    (existing) — add OrderRequest, ModifyOrderRequest,
│                                              CancelOrderRequest, ClosePositionRequest,
│                                              OrderResult, ApprovalPreview
├── errors.py                   (existing) — add factories: requires_approval (returns the
│                                              preview, NOT an error), invalid_approval_error,
│                                              exceeds_local_limit_error,
│                                              idempotency_diverged_error,
│                                              invalid_ticket_error
├── config.py                   (existing) — add platformdirs default for storage paths;
│                                              expose policy.* and idempotency.* fields
└── server.py                   (existing) — wire PolicyEngine into AppContext
```

**`AppContext` grows by one field**: `policy: PolicyEngine`. Built in `build_context()`, owns the SQLite connection (idempotency) and the JSONL writer (audit). The autouse `_reset_app_context` test fixture in `tests/conftest.py` already tears down per-test state; the engine's resources (DB connection, file handle) are closed in the existing teardown path.

**Storage paths**, defaulted via `platformdirs.user_data_dir("mt5-mcp")`:
- `idempotency.path` → `<user_data>/idempotency.db`
- `audit.path` → `<user_data>/audit.jsonl`

Both overridable in `config.toml`. Existing `[idempotency]` and `[audit]` sections grow a `path` key.

---

## 4. Type system additions

All in `mt5_mcp/types.py`, using the Phase-1 `_DecimalStr` alias and `_Base` validators (aware-UTC, no float→Decimal coercion).

```python
class OrderRequest(_Base):                  # place_order inputs
    symbol: str
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop", "stop_limit"]
    volume: _DecimalStr
    price: _DecimalStr | None               # required for limit / stop / stop_limit
    stop_limit_price: _DecimalStr | None    # required for stop_limit
    sl: _DecimalStr | None = None
    tp: _DecimalStr | None = None
    deviation: int = 10                     # market-order slippage in points
    comment: str | None = None
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None

class ModifyOrderRequest(_Base):            # covers pending orders + position SL/TP
    ticket: int
    sl: _DecimalStr | None = None
    tp: _DecimalStr | None = None
    price: _DecimalStr | None = None        # pending orders only
    expiration: datetime | None = None
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None

class CancelOrderRequest(_Base):            # NO consent gate (reduces exposure)
    ticket: int
    idempotency_key: str | None = None

class ClosePositionRequest(_Base):
    ticket: int
    volume: _DecimalStr | None = None       # None = close in full
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None

class ApprovalPreview(_Base):               # returned when consent gate trips
    request_id: str                         # ULID
    expires_at: datetime
    summary: str                            # "BUY 0.5 EURUSD @ market (~$54k)"
    action: Literal["place_order", "modify_order", "close_position"]
    symbol: str
    notional: _DecimalStr                   # in account currency
    estimated_margin: _DecimalStr           # notional / leverage; best-effort
    reference_quote: Quote                  # bid/ask snapshot at preview time
    request_echo: dict[str, Any]            # full input for the human to inspect

class OrderResult(_Base):                   # returned by all four mutating tools
    success: bool
    ticket: int | None
    action: str
    symbol: str
    volume: _DecimalStr
    price_filled: _DecimalStr | None
    request_echo: dict[str, Any]
    replayed: bool = False                  # true when result came from idempotency cache
    error: ErrorDetail | None = None
    server_response_code: int               # mt5lib retcode; 10009 = TRADE_RETCODE_DONE
```

Field naming notes:
- `request_echo` (not `requested`, as the architecture doc shows) — clearer that it is a sanitised echo of inputs (the `idempotency_key` is stripped to avoid logging it twice).
- `replayed: bool` — explicit field for `IDEMPOTENCY_REPLAY` semantics. Better than a hidden marker in `request_echo` because agents can branch on `result.replayed` directly.

---

## 5. PolicyEngine API

Single facade for the entire Phase-2 pipeline:

```python
class PolicyEngine:
    """Orchestrates preflight → consent → idempotency → execute → audit."""

    def __init__(
        self,
        config: Config,
        broker_offset_minutes_provider: Callable[[], int],
        account_info_provider: Callable[[], AccountInfo | None],
    ) -> None: ...

    @contextmanager
    def guard(
        self,
        action: Literal["place_order", "modify_order", "cancel_order", "close_position"],
        request: BaseModel,                          # the typed request model
        *,
        requires_approval: bool,                     # tool computed it; engine doesn't bake gate logic
        preview_factory: Callable[[], ApprovalPreview] | None = None,
        preflight_inputs: PreflightInputs | None = None,  # account + daily P&L; None for cancel_order
    ) -> Iterator["GuardedExecution"]:
        """Drives the full pipeline.

        Tool responsibilities (computed BEFORE calling guard):
        - `requires_approval`: gate logic varies per action — place_order /
          close_position use notional-vs-threshold; modify_order uses the
          SL/TP widening rule; cancel_order is always False. The engine
          does NOT bake this logic in.
        - `preview_factory`: invoked only when requires_approval=True AND
          the request lacks approval_confirmed=True. May fetch a tick.

        Engine responsibilities (in this order):
        1. Compute canonical request hash (excluding approval_* fields)
           for idempotency lookup / divergence detection.
        2. If `request.idempotency_key` is set: check cache.
           - Hit + same hash → short_circuit = cached OrderResult with
             `replayed=True`. Audit logs `action="replay"`.
           - Hit + different hash → short_circuit = IDEMPOTENCY_DIVERGED.
             Audit logs `action="idempotency_diverged"`.
        3. Run preflight checks (preflight_inputs + config). On fail →
           short_circuit = EXCEEDS_LOCAL_LIMIT envelope. Audit logs
           `action="preflight_refused"`.
        4. If `requires_approval=True`:
           - When `request.approval_confirmed=False`: call preview_factory(),
             store the preview keyed by its new ULID, short_circuit = the
             preview dict. Audit logs `action="requires_approval"`.
           - When `approval_confirmed=True`: look up the stored preview by
             `approval_request_id`, validate retry matches (price drift,
             expiry, identical fields). On mismatch → short_circuit =
             INVALID_APPROVAL. Audit logs `action="invalid_approval"`.
           - On match: discard the stored preview; proceed to execute.
        5. All gates passed → yield GuardedExecution. Tool body calls
           `g.execute(callback)` to run the mt5 RPC, then `g.finalize(...)`
           which audit-logs `action="executed"` and (if idempotency_key set)
           caches the resulting OrderResult.
        """
```

`GuardedExecution` is a small sidecar class with three members the tool body uses:
- `g.short_circuit: dict | None` — when set, return it directly.
- `g.execute(callback) -> Any` — runs the callback (the `mt5.order_send()` call), times it, captures errors. Re-raises `MT5Error` so `error_envelope` catches it.
- `g.finalize(raw_to_result_fn, *, request_echo: dict) -> dict` — converts the raw mt5 response to an `OrderResult` (using the supplied conversion function), writes the audit line, caches the idempotency entry, and returns `result.model_dump(mode="json")`.

`PreflightInputs` is a small dataclass holding the account snapshot (balance, equity, leverage, currency) plus the running daily realised P&L; built once per tool call and passed in. The engine writes audit lines for every short-circuit path AND for executed paths; the tool body never calls audit directly.

---

## 6. Tool body — `place_order` walkthrough

```python
@mcp.tool()
@error_envelope
def place_order(
    symbol: str, side: str, type: str, volume: str,
    price: str | None = None, stop_limit_price: str | None = None,
    sl: str | None = None, tp: str | None = None, deviation: int = 10,
    comment: str | None = None, idempotency_key: str | None = None,
    approval_confirmed: bool = False, approval_request_id: str | None = None,
) -> dict:
    ctx = get_context()
    req = OrderRequest(symbol=symbol, side=side, type=type,
                       volume=Decimal(volume), price=Decimal(price) if price else None,
                       ...)

    # Adapter prep — raises MT5Error caught by error_envelope.
    info = ctx.symbols.get(symbol)
    ctx.symbols.validate_volume(symbol, req.volume)
    if req.price is not None:
        req = req.model_copy(update={"price": ctx.symbols.quantise_price(symbol, req.price)})
    filling = ctx.symbols.pick_filling_mode(symbol, order_type=req.type)

    # Tool-side gate logic: compute requires_approval. For place_order,
    # the rule is notional ≥ auto_approve_notional. We need a reference
    # price for that — for limit/stop orders the request carries it; for
    # market we fetch one tick.
    if req.price is not None:
        ref_price = req.price
        ref_tick = None
    else:
        ref_tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        ref_price = Decimal(str(ref_tick.ask if req.side == "buy" else ref_tick.bid))
    notional = req.volume * ref_price
    requires_approval = notional >= ctx.config.policy.auto_approve_notional

    def build_preview() -> ApprovalPreview:
        # Re-fetch a fresh tick for the preview so the reference_quote
        # stored against the ULID is current at preview time.
        tick = ref_tick or ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        return ApprovalPreview(
            request_id=ulid_new(),
            expires_at=now_utc() + timedelta(minutes=5),
            summary=f"{req.side.upper()} {req.volume} {symbol} @ {req.type} (~{notional} {account.currency})",
            action="place_order", symbol=symbol, notional=notional,
            estimated_margin=notional / Decimal(str(account.leverage)),
            reference_quote=Quote(symbol=symbol, bid=Decimal(str(tick.bid)),
                                   ask=Decimal(str(tick.ask)),
                                   time=epoch_to_utc(tick.time, ctx.client.broker_offset_minutes)),
            request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
        )

    preflight = build_preflight_inputs(ctx, action="place_order", notional=notional)

    with ctx.policy.guard(
        "place_order", req,
        requires_approval=requires_approval,
        preview_factory=build_preview if requires_approval else None,
        preflight_inputs=preflight,
    ) as g:
        if g.short_circuit is not None:
            return g.short_circuit
        mt5_dict = order_request_to_mt5_dict(req, info, filling)
        raw = g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
        return g.finalize(order_result_from_mt5_response,
                          request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}))
```

The other three tools follow the same shape with their own request type, adapter prep (e.g. `modify_order` looks up the existing position/order via `mt5.positions_get(ticket=...)` / `mt5.orders_get(ticket=...)`), and preview-factory (close_position uses `current_price`, modify_order uses position notional only when widening SL/TP).

---

## 7. Approval-gate semantics

| Action | Gates? | Notional basis |
|---|---|---|
| `place_order` | Yes, when notional ≥ `auto_approve_notional` | `volume * (ask if side==buy else bid)` |
| `close_position` | Yes, when notional ≥ `auto_approve_notional` | `volume * current_price` |
| `modify_order` | Yes, **only when widening or removing SL/TP** | position-or-order notional at current market |
| `cancel_order` | Never | n/a |

**SL/TP widening rule** (modify_order): the gate trips when the new `sl` or `tp` is **further from the current price** than the existing one (less protective), or **null when the existing one was set**. Tightening stops auto-approves regardless of notional.

### Hard refusals (no `approval_confirmed` overrides these)

- `volume * price > policy.max_notional_per_trade` → `EXCEEDS_LOCAL_LIMIT`.
- Symbol in `symbols.denylist` → `EXCEEDS_LOCAL_LIMIT`.
- `symbols.allowlist` non-empty AND symbol not in it → `EXCEEDS_LOCAL_LIMIT`.
- `close_position` realised loss > `policy.max_realised_loss_per_close` → `EXCEEDS_LOCAL_LIMIT`.
- `place_order` running daily realised P&L would push past `-max_daily_loss` → `EXCEEDS_LOCAL_LIMIT`.

**Daily P&L day boundary**: broker-server-day, not UTC-day, not local-machine-day. Computed as:

```
broker_now      = utc_now() + timedelta(minutes=broker_offset_minutes)
broker_day_0    = broker_now.replace(hour=0, minute=0, second=0, microsecond=0)
utc_day_start   = broker_day_0 - timedelta(minutes=broker_offset_minutes)
```

`broker_offset_minutes` comes from the cached value set in `MT5Client.connect()`. Realised P&L is `sum(deal.profit + deal.swap + deal.commission)` over `history_deals_get(date_from=broker_day_0_naive, date_to=broker_now_naive)` (mt5lib expects naive timestamps in broker-local time).

### Retry-validation tolerance (when `approval_confirmed=true` arrives)

- Identical: `action`, `symbol`, `side`, `type`, `volume`, `ticket` (where applicable).
- Price: within `max(0.5% of reference_quote, deviation_points * symbol.point)` — preserves intent for market orders that explicitly allow slippage.
- `approval_request_id` matches a stored, un-expired preview.
- Mismatch → `INVALID_APPROVAL` envelope with `details.reason` describing the violation.

---

## 8. Idempotency store

SQLite, WAL mode, single-process safe.

```sql
CREATE TABLE IF NOT EXISTS idempotency (
    key             TEXT PRIMARY KEY,        -- agent-supplied opaque string (no format constraint)
    action          TEXT NOT NULL,           -- "place_order" etc.
    request_hash    TEXT NOT NULL,           -- SHA256 of canonical JSON of the typed request,
                                             -- excluding approval_* fields (those vary by retry)
    result_json     TEXT NOT NULL,           -- the cached OrderResult JSON
    created_at      INTEGER NOT NULL,        -- unix epoch
    expires_at      INTEGER NOT NULL
);
CREATE INDEX idx_expires_at ON idempotency(expires_at);
```

- **Without an `idempotency_key`**: no caching. Every call executes; tool docstrings encourage agents to pass a UUIDv4.
- **TTL**: `idempotency.ttl_seconds` from config (default 86 400 = 24 h).
- **In-band cleanup**: each lookup deletes rows with `expires_at < now()` for the lookup's `action`. No background sweeper — keeps the implementation simple and the DB size bounded.
- **Replay rule**: same `key` AND same `request_hash` → return the cached `result_json` deserialised, with `result.replayed = True` set. A successful replay looks successful to the agent (no error envelope); the boolean lets it branch on "did this actually execute or did we get the cached version?"
- **Divergence**: same key, different hash → `IDEMPOTENCY_DIVERGED` error. This surfaces agent bugs (caller forgot to vary the key between distinct trades) instead of silently masking them.
- **Concurrency**: `BEGIN IMMEDIATE` on insert. FastMCP is single-process; the WAL handles internal-thread interleaving.

---

## 9. Audit log

JSONL append-only at `audit.path`. Every tool call logs one event. Read-tool events log only `{tool, action: "called"}` — no result body (would dominate disk). Mutating-tool events log full request, status, and timing.

```json
{"ts":"2026-04-26T10:30:00Z","tool":"place_order","action":"executed",
 "request":{"symbol":"EURUSD","side":"buy","type":"market","volume":"0.10",...},
 "result_status":"filled","ticket":12345,"duration_ms":142,
 "approval_request_id":null,"idempotency_key":"01HX...","request_hash":"sha256:..."}
```

`action` enum: `executed`, `requires_approval`, `replay`, `preflight_refused`, `invalid_approval`, `idempotency_diverged`, `error`, `called` (read tools).

**Rotation**: when `os.path.getsize(audit.path) > audit.max_bytes` (default 10 MB), rename to `audit.jsonl.<unix_epoch>` and open a fresh handle. No compression in Phase 2; rotated files persist on disk indefinitely (operator's choice when to archive). One audit writer per process; an `RLock` guards the rotation+write transition.

---

## 10. Error codes (factories in `errors.py`)

| Code | When | retryable | requires_human |
|---|---|---|---|
| `EXCEEDS_LOCAL_LIMIT` | Pre-flight refusal (notional, allow/denylist, daily loss, realised loss). `details.limit_name` identifies which. | false | true |
| `INVALID_APPROVAL` | `approval_confirmed=true` retry doesn't match stored preview (price drift, expiry, identical-fields mismatch). | true | true |
| `IDEMPOTENCY_DIVERGED` | Same `idempotency_key`, different request hash. | false | true |
| `INVALID_TICKET` | `modify_order` / `cancel_order` / `close_position` ticket doesn't exist. | false | false |

`REQUIRES_APPROVAL` is **not** an error envelope — it returns the `ApprovalPreview` directly. Architecturally distinct: errors mean "this won't work"; the preview means "we paused; tell us if you want to proceed."

`IDEMPOTENCY_REPLAY` is also not an error — replays return the cached `OrderResult` with `replayed=True`. The boolean field is the canonical marker.

---

## 11. Testing strategy

### Extending `tests/fakes.py`

```python
@dataclass
class FakeOrderSendResult:
    retcode: int = TRADE_RETCODE_DONE       # 10009
    order: int = 0                          # ticket of created order
    deal: int = 0                           # ticket of resulting deal (market orders)
    volume: float = 0.0
    price: float = 0.0
    comment: str = ""
    request_id: int = 0
```

`FakeMT5` gains:
- `_order_send: FakeOrderSendResult | None` slot.
- `order_send(request)` recording the dict in `calls["order_send"]` as a **list** (`list[dict]`), not a counter — tests need to inspect what was sent on each retry/replay.
- `positions_get(ticket=...)` / `orders_get(ticket=...)` already work; tests populate `_positions_get` / `_orders_get`.

### New test files

- `test_policy_preflight.py` — limit checks in isolation. Stubs `Config` + a fake `account_info_provider`; no `FakeMT5` needed.
- `test_policy_consent.py` — preview generation, ULID format, expiry, drift, identical-fields validation, INVALID_APPROVAL paths.
- `test_policy_idempotency.py` — fresh-cache write, replay (same key/hash), divergence (same key/different hash), TTL eviction (in-band on lookup), no-key-no-cache.
- `test_policy_audit.py` — JSONL line shape per `action`, size-based rotation triggers rename, concurrent appenders use the lock.
- `test_tools_place_order.py` — full pipeline: small notional auto-approves; over threshold returns preview; retry with approval_confirmed succeeds; price drift breaks INVALID_APPROVAL; pre-flight notional cap blocks regardless of approval; idempotency replay.
- `test_tools_modify_order.py` — pending order limit-price change; position SL widening trips gate; SL tightening auto-approves; INVALID_TICKET.
- `test_tools_cancel_order.py` — no gate; idempotent.
- `test_tools_close_position.py` — partial close; full close; realised-loss hard cap.

### Existing test patterns to preserve

- Hand-rolled fakes only — no `unittest.mock.MagicMock` (per `tests/fakes.py` precedent + memory note).
- UTC-portable epochs only: `int(datetime(..., tzinfo=timezone.utc).timestamp())`.
- Autouse `_reset_app_context` fixture handles per-test isolation (extends to `PolicyEngine` cleanup).
- All datetimes flow through `adapter/conversions.py::epoch_to_utc`.

---

## 12. Architecture-doc reconciliation (in-band edits as part of Phase 2)

These doc edits ship in the same Phase 2 commits, not a separate task:

- **§8.1 (consent gate)** — replace HMAC-token text with the simple `approval_confirmed` flag + retry-matches-preview model. Make explicit that the consent gate is a UX/policy affordance, not a cryptographic control. Trust boundary is the transport.
- **§8.2 (limits)** — rename "Soft limits" → "Pre-flight limits" with the explicit "not a security control" framing. The broker's MT5 server is the real boundary.
- **§8.3 (idempotency)** — clarify SQLite path is per-OS via `platformdirs`; document divergence detection.
- **§8.4 (audit)** — clarify rotation behavior and the `action` enum.
- **§9** — keep HTTP transport as Phase 3 (per CLAUDE.md). No edits beyond clarifying the phase boundary.

---

## 13. Out of scope for Phase 2 (deferred to Phase 3+)

- **Resources** (`account://current`, `positions://current`, `quotes://{symbol}`).
- **HTTP+SSE transport** (Tailscale deployment).
- **`modify_position` as a separate tool** — folded into `modify_order`'s SL/TP path per architecture §5 line 185.
- **Queryable audit-log CLI** (`mt5-mcp audit tail/grep`). JSONL is tail-friendly enough for v0.2.
- **`pick_filling_mode` improvements** beyond the existing FOK/IOC/RETURN logic (Phase 1).
- **Multi-leg / OCO / partial-fill orchestration**.
- **Background TTL sweeper** for idempotency. In-band cleanup is sufficient at expected request volumes.
- **Audit log compression**. Operators rotate manually.
- **Migrating off `_tool_manager` private API** in tests. Wait for FastMCP to ship a public sync accessor.

---

## 14. Definition of done

- All four mutating tools registered, callable end-to-end against `FakeMT5`.
- `PolicyEngine` covers preflight + consent + idempotency + audit, with isolated unit tests for each module.
- Test count grows from 91 (Phase 1) by ~40-60 new tests; full suite green in <3s.
- `doctor` CLI extended with one place_order + close_position round-trip in demo mode (skipped if no terminal).
- Architecture doc §8.* reconciled (HMAC removed, "soft" → "pre-flight" rename).
- CLAUDE.md "Critical patterns" updated with the `ctx.policy.guard(...)` pattern and any new gotchas surfaced during implementation.
- Tagged `phase-2-complete`; commit pushed to `main`.
