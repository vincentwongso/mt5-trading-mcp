# Phase 3 — Resources and HTTP Transport

**Status:** Design approved 2026-04-27. Awaits implementation plan (`writing-plans`).
**Owner:** Vincent
**Phase 2 commit:** `6cf242b` (carryover items closed)
**Architecture spec:** `mt5-mcp-architecture.md` §15 (phase order), §16 q4 (quote-subscription poll-and-emit model)

---

## 1. Goal

Ship three subscribable MCP resources (`account://current`, `positions://current`, `quotes://{symbol}`) and an opt-in HTTP/SSE transport on top of Phase 1+2. A single shared poller drives change-detection for all three resources; subscribers receive `notifications/resources/updated` and re-read the resource for the fresh snapshot. STDIO remains the default transport; HTTP is selected via a new `serve --transport http` subcommand.

Phase 3 closes when:

1. All three resources are subscribable end-to-end against `FakeMT5` with diff-based notification fanout.
2. `--transport http` boots a streamable-HTTP server bound to loopback with optional bearer-token auth.
3. `doctor` includes a `[streaming]` check that runs the poller for ~1s against the live terminal and confirms a tick was diffed.
4. Full unit suite plus one HTTP-transport integration test green; Phase 1 + Phase 2 tests still pass.

This is a single-tag delivery: `phase-3-complete`. Plugin loader is **deferred to Phase 4**.

---

## 2. Foundation decisions (locked during brainstorm)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Plugin loader deferred to Phase 4.** Phase 3 ships Resources + HTTP only. | Plugin extensibility is orthogonal to "what the MCP exposes today". Bundling it with transport work risks scope sprawl; better to give plugin design its own focused phase. |
| 2 | **Single shared poller, one daemon thread.** Symbol set, account snapshot, positions list all polled by the same loop. | MT5 IPC isn't free; one shared poller bounds load by symbols-of-interest, not subscriber count. One source of truth for "current tick"; one error path; one metrics surface. |
| 3 | **Default poll cadence 200ms for quotes, 1s for account/positions, configurable.** | 200ms is fast enough for human-pace agent reactions; ≥5Hz aligns with architecture §16 q4. Account/positions only fire on identity/structural changes, so 1s is plenty. |
| 4 | **HTTP bind = loopback only in Phase 3, bearer token optional.** Non-loopback host raises `ConfigError` at startup. | Local-first posture (per CLAUDE.md). Bearer token gives multi-agent isolation on the same machine without committing to a remote-deployment story. LAN/remote use case can be added in Phase 4 if a customer asks. |
| 5 | **STDIO stays the default transport.** HTTP is opt-in via `--transport http`. | Switching the default would break every existing MCP client config. STDIO is what Claude Desktop / Claude Code wire up by default. |
| 6 | **All three resources subscribable.** | Subscribable account+positions removes "did my SL hit?" polling from the agent's responsibility. The shared-poller architecture makes the marginal cost cheap. |
| 7 | **Non-quote diffs use identity + structural fields only.** Floating P&L (`profit`, `equity`, `margin`, `price_current`) is excluded from diffs. | Floating fields drift on every tick; including them would fire `positions://current updated` ~5×/sec per position during chop. Subscribers who care about P&L compose `positions://` (entry data) with `quotes://` (current bid/ask). |
| 8 | **Read-only resources skip the policy engine.** Resource handlers go through `ctx.client.call(...)` like Phase 1 read tools — no `ctx.policy.guard`, no idempotency, no audit. | Resources are read-only by definition. Policy machinery is for mutating actions only. |

---

## 3. File layout

```
src/mt5_mcp/
├── streaming/                    (NEW package)
│   ├── __init__.py               — exports Poller, Dispatcher
│   ├── poller.py                 — class Poller (single daemon thread, diff loop)
│   ├── dispatcher.py             — class Dispatcher (subscriber registry + fanout)
│   └── snapshots.py              — TickSnapshot, AccountSnapshot, PositionSnapshot
│                                     dataclasses (the fields tracked for diffs)
├── resources/                    (NEW package)
│   ├── __init__.py               — register_all(mcp, ctx) entrypoint
│   ├── account.py                — account://current handler + subscribe hooks
│   ├── positions.py              — positions://current handler + subscribe hooks
│   └── quotes.py                 — quotes://{symbol} handler + subscribe hooks
├── transport.py                  (NEW) — run(mcp, transport, config)
├── cli.py                        (existing) — add `serve` subcommand with --transport
├── server.py                     (existing) — wire Dispatcher + Poller into AppContext;
│                                              register resources alongside tools
├── config.py                     (existing) — add [transport.http] and [streaming]
│                                              sections
├── errors.py                     (existing) — add resource_not_found(uri) factory
└── types.py                      (existing) — no new public types needed; resource
                                              handlers reuse Quote, AccountInfo, Position
                                              from Phase 1
```

**`AppContext` grows by two fields:**
- `dispatcher: Dispatcher`
- `poller: Poller`

Both built in `build_context()`. The poller is **not started at boot** — it starts lazily when the first subscription is created and stops when the last is dropped. This keeps STDIO sessions that never subscribe from running an idle thread. The autouse `_reset_app_context` test fixture in `tests/conftest.py` will tear down both fields per-test (calling `poller.stop()` is idempotent).

**Storage paths:** none. Phase 3 adds no on-disk state.

---

## 4. Snapshot dataclasses

In `streaming/snapshots.py` — internal-only, plain `@dataclass(frozen=True, slots=True)`. These are NOT the Pydantic types returned to clients (those stay in `types.py`); they exist so the diff logic doesn't have to compare full Pydantic models.

```python
@dataclass(frozen=True, slots=True)
class TickSnapshot:
    time_msc: int           # primary diff key
    bid: float
    ask: float
    last: float             # for non-FX symbols
    volume: int

@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    balance: float          # tracked
    credit: float           # tracked
    currency: str           # tracked
    # NOT tracked: equity, margin, free_margin, profit, margin_level

@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    ticket: int             # identity
    volume: float           # tracked (changes on partial close)
    sl: float               # tracked (changes on modify_order)
    tp: float               # tracked (changes on modify_order)
    # NOT tracked: price_current, profit, swap, time_update
```

Equality is structural via `@dataclass(frozen=True)` defaults — used directly for diff detection (`if new != self._last_ticks[symbol]: ...`).

---

## 5. Poller (`streaming/poller.py`)

### Public surface

```python
class Poller:
    def __init__(
        self,
        client: MT5Client,
        dispatcher: Dispatcher,
        config: StreamingConfig,
    ) -> None: ...

    def start(self) -> None:
        """Idempotent. Spawns the daemon thread if not already running."""

    def stop(self, timeout: float = 2.0) -> None:
        """Idempotent. Sets _stop, joins thread within timeout. Daemon flag
        ensures the process can exit even if join times out."""

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the quotes poll set. Sets _wake so the loop picks
        it up before the next interval. Called by Dispatcher only."""

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol. Drops _last_ticks entry. Called by Dispatcher only."""
```

### Loop body

```python
def _run(self) -> None:
    while not self._stop.is_set():
        cycle_start = monotonic()
        try:
            self._poll_quotes()
        except Exception:
            log.exception("quote poll cycle failed")
        try:
            if cycle_start - self._last_account_poll >= self._account_interval:
                self._poll_account()
                self._last_account_poll = cycle_start
        except Exception:
            log.exception("account poll cycle failed")
        try:
            if cycle_start - self._last_positions_poll >= self._positions_interval:
                self._poll_positions()
                self._last_positions_poll = cycle_start
        except Exception:
            log.exception("positions poll cycle failed")

        # Sleep until next quote tick OR until woken (new symbol added)
        elapsed = monotonic() - cycle_start
        wait = max(0.0, (self._quote_interval_ms / 1000.0) - elapsed)
        self._wake.wait(timeout=wait)
        self._wake.clear()
```

`_poll_quotes`, `_poll_account`, `_poll_positions` each catch `MT5Error` from `ctx.client.call`, increment a per-resource failure counter, and log WARNING. Three consecutive failures → fire one `dispatcher.dispatch_*_error(uri)` call (which fans out an `updated` notification; subscriber re-reads, gets the standard error envelope). A successful poll resets the counter silently.

### Diff logic

```python
def _poll_quotes(self) -> None:
    symbols = self._dispatcher.subscribed_symbols()  # snapshot under lock
    for sym in symbols:
        tick = self._client.call(lambda m: m.symbol_info_tick(sym))
        if tick is None:
            continue  # broker dropped the symbol; no notification, no failure
        snap = TickSnapshot(
            time_msc=tick.time_msc,
            bid=tick.bid,
            ask=tick.ask,
            last=tick.last,
            volume=tick.volume,
        )
        last = self._last_ticks.get(sym)
        if last != snap:
            self._last_ticks[sym] = snap
            self._dispatcher.dispatch_tick(sym, snap)
```

Account and positions diffs follow the same shape — build a snapshot, compare structurally, fire on diff.

For positions, the comparison is: build `dict[int, PositionSnapshot]` from `m.positions_get()`, compare keys-and-values to `_last_positions`. Any key delta (open/close) OR any value delta (sl/tp/volume change) fires one notification covering the whole `positions://current` resource — the subscriber re-reads the full list.

---

## 6. Dispatcher (`streaming/dispatcher.py`)

### Public surface

```python
class Dispatcher:
    def __init__(self, poller: Poller | None = None) -> None: ...
    # poller is set after construction (cyclic dependency); see § lifecycle

    def subscribe(
        self,
        uri: str,
        subscriber: Subscriber,
    ) -> SubscriptionHandle: ...

    def unsubscribe(self, handle: SubscriptionHandle) -> None: ...

    def subscribed_symbols(self) -> set[str]:
        """Snapshot under lock. Used by Poller._poll_quotes."""

    def dispatch_tick(self, symbol: str, snap: TickSnapshot) -> None: ...
    def dispatch_account(self, snap: AccountSnapshot) -> None: ...
    def dispatch_positions(self) -> None: ...

    def dispatch_quote_error(self, symbol: str) -> None: ...
    def dispatch_account_error(self) -> None: ...
    def dispatch_positions_error(self) -> None: ...

    def reap_dead_subscribers(self) -> int:
        """Belt-and-suspenders. Removes subscribers whose session.send raised
        on last fanout. Returns count reaped. Called opportunistically."""
```

### Internal state

```python
self._lock = threading.Lock()
self._subs_by_uri: dict[str, list[Subscription]]  # uri -> subscribers
self._subs_by_handle: dict[SubscriptionHandle, Subscription]
self._symbol_refcount: dict[str, int]  # for quotes://{symbol}
self._poller: Poller | None  # late-bound
```

### Fanout

```python
def dispatch_tick(self, symbol: str, snap: TickSnapshot) -> None:
    uri = f"quotes://{symbol}"
    with self._lock:
        targets = list(self._subs_by_uri.get(uri, ()))  # snapshot under lock
    # Release lock; fanout happens unlocked so a slow subscriber doesn't
    # block other subscribers from receiving the same tick.
    for sub in targets:
        try:
            sub.notify_updated(uri)
        except Exception:
            log.warning("subscriber send failed; will reap", exc_info=True)
            sub.dead = True
```

`Subscriber.notify_updated(uri)` is a thin wrapper around FastMCP's session-level `notifications/resources/updated`; FastMCP normalizes STDIO and HTTP under the same session interface, so the dispatcher doesn't know which transport it's sending over.

### Lifecycle

```python
def subscribe(self, uri, subscriber):
    handle = SubscriptionHandle(ulid_new())
    sub = Subscription(handle=handle, uri=uri, subscriber=subscriber)
    started = False
    with self._lock:
        was_empty = not any(self._subs_by_uri.values())
        self._subs_by_uri.setdefault(uri, []).append(sub)
        self._subs_by_handle[handle] = sub
        if uri.startswith("quotes://"):
            sym = uri.removeprefix("quotes://")
            self._symbol_refcount[sym] = self._symbol_refcount.get(sym, 0) + 1
            if self._symbol_refcount[sym] == 1:
                self._poller.add_symbol(sym)
        if was_empty:
            started = True
    if started:
        self._poller.start()
    return handle

def unsubscribe(self, handle):
    stopped = False
    with self._lock:
        sub = self._subs_by_handle.pop(handle, None)
        if sub is None:
            return
        self._subs_by_uri[sub.uri].remove(sub)
        if sub.uri.startswith("quotes://"):
            sym = sub.uri.removeprefix("quotes://")
            self._symbol_refcount[sym] -= 1
            if self._symbol_refcount[sym] == 0:
                del self._symbol_refcount[sym]
                self._poller.remove_symbol(sym)
        if not any(self._subs_by_uri.values()):
            stopped = True
    if stopped:
        self._poller.stop()
```

The cyclic Poller↔Dispatcher reference is broken by late-binding the Poller into the Dispatcher after both are constructed in `build_context()`.

---

## 7. Resource handlers (`resources/`)

Each module exposes a `register(mcp, ctx)` function called from `server.build_server`.

### `resources/quotes.py`

```python
def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.resource("quotes://{symbol}")
    def read_quote(symbol: str) -> Quote:
        ctx.symbols.ensure(symbol)
        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is None:
            raise MT5Error(errors.resource_not_found(f"quotes://{symbol}"))
        return tick_to_quote(tick, symbol, ctx.client.broker_offset_minutes)

    @mcp.resource("quotes://{symbol}").subscribe
    def subscribe_quote(symbol: str, subscriber: Subscriber) -> SubscriptionHandle:
        ctx.symbols.ensure(symbol)  # validate before registering
        return ctx.dispatcher.subscribe(f"quotes://{symbol}", subscriber)
```

(FastMCP's exact subscribe-hook API will be verified against current docs during implementation; if the syntax differs, the substance is the same: a per-resource subscribe callback that receives the resolved URI + the subscriber session and returns a handle.)

### `resources/account.py`, `resources/positions.py`

Same shape, fixed URIs (`account://current`, `positions://current`). Read paths reuse the Pydantic types and conversion helpers from Phase 1 (`AccountInfo`, `Position`).

### `resources/__init__.py`

```python
def register_all(mcp: FastMCP, ctx: AppContext) -> None:
    quotes.register(mcp, ctx)
    account.register(mcp, ctx)
    positions.register(mcp, ctx)
```

Called from `server.build_server` immediately after the existing `tools` registration.

---

## 8. HTTP transport (`transport.py`)

```python
def run(mcp: FastMCP, *, transport: str, config: Config) -> None:
    if transport == "stdio":
        mcp.run()
        return
    if transport == "http":
        host = config.transport.http.host
        port = config.transport.http.port
        if not _is_loopback(host):
            raise ConfigError(
                f"transport.http.host must be a loopback address in v0.3 "
                f"(got {host!r})"
            )
        token = config.transport.http.token
        if token:
            mcp.add_middleware(BearerAuthMiddleware(token))
        mcp.run(transport="streamable-http", host=host, port=port)
        return
    raise ConfigError(f"unknown transport {transport!r}")


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Hostnames: only "localhost" is allowed
        return host == "localhost"
```

`BearerAuthMiddleware` is a small Starlette middleware (FastMCP exposes Starlette under the streamable-HTTP transport):

```python
class BearerAuthMiddleware:
    def __init__(self, app, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        actual = headers.get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(actual, self._expected):
            await _send_401(send)
            return
        await self._app(scope, receive, send)
```

Constant-time comparison via `hmac.compare_digest` — bearer tokens are short enough that timing leaks are a real concern.

### CLI

`src/mt5_mcp/cli.py` gets a new `serve` subcommand:

```
python -m mt5_mcp serve [--transport {stdio,http}] [--config PATH]
```

Default transport is `stdio`. The existing implicit server entrypoint (`python -m mt5_mcp` with no subcommand) is preserved for STDIO backward compatibility but documented as legacy; new docs prefer `serve`.

---

## 9. Config additions

In `mt5_mcp.toml`:

```toml
[transport.http]
host = "127.0.0.1"
port = 8765
# token = "..."  # optional; bearer auth required if set

[streaming]
quote_poll_interval_ms = 200
account_poll_interval_ms = 1000
positions_poll_interval_ms = 1000
```

Pydantic models added to `config.py`:

```python
class HttpTransportConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    token: str | None = None

class TransportConfig(BaseModel):
    http: HttpTransportConfig = Field(default_factory=HttpTransportConfig)

class StreamingConfig(BaseModel):
    quote_poll_interval_ms: int = Field(200, ge=50, le=10000)
    account_poll_interval_ms: int = Field(1000, ge=100, le=60000)
    positions_poll_interval_ms: int = Field(1000, ge=100, le=60000)

class Config(BaseModel):  # existing
    # ... existing fields ...
    transport: TransportConfig = Field(default_factory=TransportConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
```

The 50ms floor on `quote_poll_interval_ms` is a guardrail against accidentally hammering MT5 IPC; brokers typically tick at ≤20Hz anyway.

Hot-reload (Phase 1's `watchdog`-driven config reload) MUST NOT mutate poller intervals mid-run — the poller reads its intervals once at construction. A config change that affects streaming requires restarting the server. This is documented in the README's config section.

---

## 10. Error handling

| Failure | Behavior |
|---|---|
| Subscribe to non-existent symbol | `RESOURCE_NOT_FOUND` returned synchronously from the subscribe handler. Dispatcher untouched. New `errors.resource_not_found(uri)` factory mirrors `terminal_not_connected_error()`. |
| MT5 disconnect mid-poll | `ctx.client.call` reinit fires; if reinit fails, `MT5Error(TERMINAL_NOT_CONNECTED)` propagates. Poller catches per-resource, logs WARNING, increments failure counter, skips cycle. |
| 3 consecutive poll failures for a resource | One `dispatcher.dispatch_*_error(uri)` call fires `notifications/resources/updated`; subscriber re-reads, the read handler's own `ctx.client.call` returns the standard error envelope. Failure counter clears on next successful poll (silently — no "we're back" notification). |
| HTTP bearer token missing/wrong | 401 from middleware; request never reaches FastMCP. Constant-time comparison. |
| HTTP non-loopback host configured | `transport.run()` raises `ConfigError` at startup; `serve` subcommand prints the error and exits non-zero before the server boots. |
| Subscriber session-write fails | Caught in `Dispatcher.dispatch_*` fanout, subscription marked `dead=True`, reaped on next opportunistic sweep. |
| Slow subscriber | Fanout is sequential per-tick; one slow subscriber blocks subsequent subscribers' notifications for THAT tick only (the lock is released before fanout, so the next tick's fanout starts on schedule). We do not queue per-subscriber. |

`_RES_IPC_TIMEOUT` from `mt5_client.py` (removed in Phase 1 carryover) stays removed — Phase 3 doesn't reintroduce IPC-timeout retry logic. The poller's "skip on failure" model handles transient IPC issues without a separate retry layer.

---

## 11. Edge cases

1. **Symbol re-selection drops mid-session.** `symbol_info_tick()` returns `None` even though `symbol_select()` succeeded earlier. Treated as no-change-this-cycle; no notification, no failure counter increment. A real disconnect raises `MT5Error`, which IS the failure path.
2. **Position closed by broker (SL/TP hit) between polls.** Identity diff catches the disappearance, fires `positions://current updated`. P&L landing in the account snapshot fires `account://current updated` independently because `balance` changed. The two notifications can arrive in either order; subscribers should treat them independently.
3. **Rapid subscribe/unsubscribe of same symbol.** `_wake` is a `threading.Event`; coalescing is fine. Worst case the poller wakes, sees the symbol already gone, and goes back to sleep without firing.
4. **Two subscribers, same symbol.** Refcount goes 1→2; no MT5 work, no `_wake` (the poller is already polling that symbol). Both subscribers get every tick notification.
5. **Subscribe to `quotes://EURUSD` while another agent's mutating tool is mid-trade on the same symbol.** No interaction. Mutating tools go through `ctx.policy.guard`; resource subscriptions go through `ctx.dispatcher`. The poller calls `ctx.client.call` exactly like everything else, so the singleton MT5 connection serializes naturally.
6. **STDIO process death with active subscriptions.** Daemon thread dies with the process; no explicit cleanup needed.
7. **HTTP connection drops with active subscriptions.** FastMCP's session lifecycle fires teardown; the Dispatcher's session-teardown hook unsubscribes every handle owned by that session. Refcounts decremented; poller stops if no subscriptions remain.
8. **Hot-reload of config.toml changes `quote_poll_interval_ms`.** Has no effect on the running poller (intervals are read once at construction). README documents that streaming-config changes require a server restart.
9. **Clock skew with broker.** Tick `time_msc` is broker time but only used for diff detection (`last == new`). UTC conversion happens in the read-path handler via existing `epoch_to_utc(...)`, not in the poller hot path.

---

## 12. Testing strategy

### Unit tests (added)

- `tests/test_streaming_poller.py` — drive `Poller` against `FakeMT5` with a small symbol set, advance `_wake`, assert poll → diff → dispatcher calls. Use a `FakeDispatcher` that records calls. Cases: tick-change fires; no-change skips; MT5 error skips + counts; three-strikes fires error notification; recovery clears counter; account poll honours its slower interval; positions diff identifies new/closed/sl-changed/tp-changed/volume-changed.
- `tests/test_streaming_dispatcher.py` — pure unit. `Dispatcher` against fake subscribers (in-memory list-of-notifications). Cases: subscribe/unsubscribe lifecycle; refcounting (1→2→1→0); slow subscriber doesn't block others; dead subscriber reaped on next dispatch; multiple URIs isolated.
- `tests/test_resources_account.py` — read-path test using `FakeMT5`; subscribe-path uses `FakeDispatcher`. Mirrors `test_tools_account.py` shape.
- `tests/test_resources_positions.py` — same.
- `tests/test_resources_quotes.py` — same; covers symbol-not-found returning `RESOURCE_NOT_FOUND`.
- `tests/test_transport.py` — config-driven. STDIO mode: `mcp.run()` called with no transport. HTTP mode: middleware installed iff token set; non-loopback host raises `ConfigError`; unknown transport raises `ConfigError`.
- `tests/test_errors.py` (existing) — extend to cover new `resource_not_found` factory.

### Integration test (added)

- `tests/test_transport_http_integration.py` — boots the server in a thread on a random port, connects with `httpx`, does `resources/list` over streamable-HTTP, subscribes to `quotes://EURUSD`, mutates a `FakeMT5` tick on the running `AppContext`, asserts the SSE stream emits one `notifications/resources/updated` carrying that URI. Marked `@pytest.mark.integration` so it can be skipped if flaky in CI.

### `FakeMT5` extensions

Adds a `_tick_overrides: dict[str, FakeTick]` slot so tests can mutate ticks between poller cycles, and an `_account_overrides: FakeAccountInfo | None` slot for account snapshot tests. Positions are already mutable on `FakeMT5` from Phase 2.

### Doctor

`doctor` gets a `[streaming]` check: builds a fresh AppContext + Dispatcher + Poller, subscribes to one of the configured smoke symbols (defaults to `EURUSD` if unconfigured), runs the poller for ~1s, asserts `>=1` tick was diffed and dispatched. Surfaces broker-side weirdness (e.g., a broker that doesn't update `time_msc` correctly) before customers hit it. New CLI flag is NOT needed — the check runs in the standard `doctor` flow.

`doctor --smoke-trade` is unchanged; Phase 3 doesn't touch the mutating-trade path.

---

## 13. Out of scope (Phase 4+)

- **Plugin loader for third-party tools.** Architecture §15 lists it under Phase 3, but it's deferred per Foundation Decision #1.
- **HTTP transport binding to non-loopback hosts.** Refused at config-load time. LAN/remote deployment story waits for an explicit customer ask in Phase 4.
- **Per-subscriber backpressure / outbox queues.** Sequential fanout is fine for the local-first deployment model. Add only if we see actual subscriber-blocking-other-subscribers problems.
- **Custom error notifications carrying `ErrorDetail` payloads.** MCP `notifications/resources/updated` is data-free by spec; the read path is where errors surface. Don't invent a new notification shape.
- **Subscribable history / orders resources.** History is one-shot read; no streaming benefit. `orders://current` (pending orders) could be added later if a customer asks.
- **TLS for HTTP transport.** Bind-loopback negates the need; a customer who wants TLS in Phase 4 should run a reverse proxy (nginx, caddy) in front.
- **Audit-log compression / archival CLI.** Carryover from Phase 2; remains Phase 4 polish.
- **Background TTL sweeper for idempotency.** Carryover from Phase 2; remains deferred until evidence of unbounded growth.

---

## 14. Architecture doc updates

`mt5-mcp-architecture.md` needs four reconciliations after Phase 3 ships:

1. **§15 (phase order):** move plugin loader from Phase 3 to Phase 4.
2. **§16 q4 (quote subscriptions):** mark resolved — single shared poller at 200ms default, configurable. Reference the new `[streaming]` config section.
3. **New §6.x or §7.x (Streaming subsystem):** brief paragraph describing the Poller + Dispatcher pattern, lazy start, and the change-detection rules (identity + structural for non-quote, full snapshot diff for quotes).
4. **New §7.x (HTTP transport):** brief paragraph describing the loopback-only constraint, bearer-token middleware, and the `serve --transport http` CLI shape.

These updates land in the same commit as the Phase 3 implementation.

---

## 15. Key invariants Phase 3 must preserve

Carried forward from Phase 1+2 CLAUDE.md and reinforced in Phase 3 review:

1. **`error_envelope` decorator pattern is tools-only.** Resource read handlers do NOT use `@error_envelope` — that decorator wraps tool returns into a Pydantic content envelope, which is the wrong shape for resources. Resource handlers raise `MT5Error(errors.<factory>(...))` and FastMCP turns the raised error into the MCP-protocol `error` response automatically. The `get_context()` first-line pattern from Phase 1 still applies to resource handlers (they need access to `ctx.client`, `ctx.symbols`, `ctx.dispatcher`). Subscribe callbacks likewise raise rather than envelope.
2. **`ctx.client.call(...)` for all mt5lib data calls.** The poller calls through `client.call`, NOT `client.mt5.<method>` directly. Constants (`m.SYMBOL_FILLING_FOK` etc.) and `ping` remain the exceptions.
3. **Aware-UTC datetimes only.** Tick timestamps reaching the client go through `epoch_to_utc`. Poller diff logic uses raw `time_msc` integers — no datetime conversion in the hot path.
4. **Production code MUST NOT import from `tests.`.** Snapshot dataclasses live in `streaming/snapshots.py`, not `tests/fakes.py`.
5. **Storage paths from config; no hard-coded paths.** Phase 3 adds no on-disk storage, but the principle holds for any future addition.
6. **Test fakes, not `MagicMock`.** New tests extend `FakeMT5` with the override slots described in §12 — no `unittest.mock` reach-throughs.

---

*End of design. Hand to `superpowers:writing-plans` to produce the implementation plan.*
