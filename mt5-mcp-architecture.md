# mt5-mcp — Architecture

**Open-source MCP server wrapping the MetaTrader 5 Python library.**

**Repo:** `github.com/fintrixmarkets/mt5-mcp` (proposed)
**Licence:** MIT
**Status:** v0.1 architecture draft
**Owner:** Vincent - Fintrix Markets
**Audience:** Implementers (Claude Code, contributors, integrators)

---

## 1. What this is and why it exists

`mt5-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that exposes a customer's local MetaTrader 5 terminal as a set of tools an AI agent can call.

It wraps the official [`MetaTrader5` Python library](https://pypi.org/project/MetaTrader5/) (henceforth `mt5lib`) — the same library institutional traders use for algorithmic strategies — and presents its surface as MCP tools (`get_account_info`, `place_order`, `close_position`, etc.) plus a small set of MCP resources for live state.

**Why it exists:**

1. **Most retail forex/CFD brokers expose MT5 to clients but not directly to AI agents.** Their HTTP APIs cover account management and deposits but stop at trading. There's no broker-agnostic, standards-based way for an agent to actually place trades.
2. **MT5 itself has no MCP server.** Existing community wrappers are either closed-source SDKs (cTrader Open API), broker-specific (custom MT5 manager APIs), or web-API gateways (mtsocketapi, mt5-rest) that require server-side deployment and broker cooperation.
3. **`mt5lib` already runs locally**, already authenticates against the customer's broker, and already executes against the broker's liquidity. Wrapping it in MCP is a thin translation layer — not a new trading system.

The project is open-source and broker-agnostic by design. Any broker's customers can use it. Fintrix is the launch reference user; nothing in the codebase should be Fintrix-specific.

---

## 2. Design principles

These are non-negotiable. Every implementation decision should be traceable back to one of these.

1. **Local-first.** The MCP server runs on the customer's machine, in the same process tree as their agent runtime. No cloud component. No telemetry by default.
2. **Reuse existing authentication.** Customer is already logged into MT5 terminal. Don't store credentials, don't manage sessions, don't proxy logins. Read the existing terminal state.
3. **Read tools have no consent gate; mutating tools do.** Reading positions is safe and frequent. Placing orders requires consent — configurable per customer.
4. **Server-side is the security boundary, not the MCP.** Hard limits (max position, max daily loss, max leverage) live in the broker's MT5 server. MCP-side limits are UX feedback, not security.
5. **Broker-agnostic.** No hardcoded broker URLs, MT5 server names, symbol conventions. Customer or agent provides them.
6. **Minimal tool surface.** Ship 12 tools, not 50. Every tool must have a clear "agent reaches for this" use case. Power users can extend via the plugin hook.
7. **Honest about constraints.** Windows-only at v1. Document the WSL2 / VM path for Mac/Linux. Don't pretend portability we don't have.
8. **Standard MCP, no extensions.** Use the official Python `mcp` SDK. No custom protocols. Any MCP-compatible client should work.
9. **Human-readable everything.** Tool descriptions, error messages, logs — all written so a human reading them can reason about what happened.

---

## 3. System overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Customer's machine (Windows)                                        │
│                                                                      │
│  ┌──────────────────────┐       ┌──────────────────────┐            │
│  │  Agent runtime       │       │  MT5 Terminal        │            │
│  │  (Claude Desktop /   │       │  (Windows .exe,      │            │
│  │  OpenClaw / Cursor / │       │  logged into broker) │            │
│  │  custom MCP client)  │       │                      │            │
│  └──────────┬───────────┘       └──────────┬───────────┘            │
│             │ MCP                           │ IPC                    │
│             │ (stdio)                       │ (named pipes)          │
│             ▼                               ▲                        │
│  ┌──────────────────────────────────────────┴─────────┐             │
│  │              mt5-mcp (Python process)              │             │
│  │                                                     │             │
│  │  ┌────────────────────────────────────────────┐    │             │
│  │  │  MCP server (stdio transport)              │    │             │
│  │  └────────────────────────────────────────────┘    │             │
│  │  ┌────────────────────────────────────────────┐    │             │
│  │  │  Policy engine (consent thresholds, soft   │    │             │
│  │  │  limits, idempotency, audit log)           │    │             │
│  │  └────────────────────────────────────────────┘    │             │
│  │  ┌────────────────────────────────────────────┐    │             │
│  │  │  mt5lib adapter (wraps MetaTrader5 calls)  │    │             │
│  │  └────────────────────────────────────────────┘    │             │
│  └─────────────────────────────────────────────────────┘             │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │   Broker MT5 Server  │
                       │   (off-machine)      │
                       │   Hard risk limits   │
                       └──────────────────────┘
```

**Process model:** MT5 Terminal must be running and logged in. `mt5-mcp` is launched on demand by the agent runtime via stdio. `mt5lib.initialize()` connects to the running terminal via Windows named pipes. Tools translate MCP calls to `mt5lib` calls and return structured JSON.

---

## 4. Module layout

```
mt5-mcp/
├── pyproject.toml
├── README.md
├── LICENCE                          MIT
├── SECURITY.md                      Threat model, disclosure
├── CHANGELOG.md
├── docs/
│   ├── installation.md              Per-platform install (Windows native, WSL2, Wine)
│   ├── client-setup.md              Claude Desktop / OpenClaw / Cursor config snippets
│   ├── tools.md                     Reference for all 12 tools (auto-generated from docstrings)
│   ├── policy.md                    Consent thresholds, soft limits, config file
│   ├── extending.md                 Plugin hooks for custom tools
│   └── examples/
│       ├── claude-desktop-config.json
│       ├── openclaw-skill.md
│       └── cursor-mcp-config.json
├── src/
│   └── mt5_mcp/
│       ├── __init__.py
│       ├── __main__.py              Entry point: `python -m mt5_mcp`
│       ├── server.py                MCP server bootstrap, transport selection
│       ├── config.py                Pydantic config model + file loader
│       ├── policy/
│       │   ├── __init__.py
│       │   ├── consent.py           Consent threshold logic
│       │   ├── limits.py            Soft client-side limits
│       │   └── idempotency.py       Idempotency key tracking
│       ├── adapter/
│       │   ├── __init__.py
│       │   ├── mt5_client.py        Thin wrapper around mt5lib (singleton, connection mgmt)
│       │   ├── symbols.py           Symbol info + market hours
│       │   └── conversions.py       mt5lib types ⇄ structured dicts
│       ├── tools/
│       │   ├── __init__.py          Tool registry
│       │   ├── account.py           get_account_info
│       │   ├── positions.py         get_positions, close_position
│       │   ├── orders.py            place_order, modify_order, cancel_order, get_orders
│       │   ├── history.py           get_history
│       │   ├── market.py            get_quote, get_symbols, get_market_hours
│       │   └── system.py            ping, get_terminal_info
│       ├── resources/
│       │   ├── __init__.py
│       │   ├── account.py           account://current
│       │   ├── positions.py         positions://current
│       │   └── quotes.py            quotes://{symbol} (subscription)
│       ├── audit/
│       │   ├── __init__.py
│       │   └── log.py               Append-only JSONL audit log
│       └── plugins/
│           ├── __init__.py
│           └── loader.py            Discover and register third-party tools
├── tests/
│   ├── conftest.py                  Pytest fixtures, mock mt5lib
│   ├── test_tools_account.py
│   ├── test_tools_orders.py
│   ├── test_policy_consent.py
│   ├── test_policy_limits.py
│   ├── test_adapter_conversions.py
│   ├── test_audit_log.py
│   └── integration/
│       ├── README.md                How to run against a real demo MT5 terminal
│       └── test_full_flow.py
└── examples/
    ├── headless_demo.py             Standalone Python script driving the MCP via stdio
    ├── place_order_with_sl.py
    └── close_all_positions.py
```

---

## 5. Tool surface (v1)

Twelve tools, two resources. Locked for v1; add more only with strong justification.

### Read-only tools (no consent gate)

| Tool | Purpose | Returns |
|---|---|---|
| `get_account_info` | Account balance, equity, margin, free margin, leverage, currency, server | `AccountInfo` |
| `get_positions` | Open positions, optional symbol filter | `list[Position]` |
| `get_orders` | Pending orders, optional symbol filter | `list[Order]` |
| `get_history` | Closed trades within a time range | `list[Deal]` |
| `get_quote` | Current bid/ask for a symbol | `Quote` |
| `get_symbols` | Tradeable instruments, optional category filter | `list[SymbolInfo]` |
| `get_market_hours` | Session status (open/closed/holiday) per symbol | `MarketHours` |
| `get_terminal_info` | Connection status, MT5 build, broker name, login | `TerminalInfo` |
| `ping` | Health check; verifies mt5lib is connected | `{ok: bool, latency_ms: int}` |

### Mutating tools (consent gate at policy threshold)

| Tool | Purpose | Returns |
|---|---|---|
| `place_order` | Market or pending order with optional SL/TP | `OrderResult` |
| `modify_order` | Change SL/TP/expiry on an existing order or position | `OrderResult` |
| `close_position` | Close in full or part by ticket | `OrderResult` |
| `cancel_order` | Cancel a pending order by ticket | `OrderResult` |

### Resources

| URI | Purpose |
|---|---|
| `account://current` | Live account snapshot, refreshed on read |
| `positions://current` | Live positions snapshot, refreshed on read |
| `quotes://{symbol}` | Quote subscription — agent receives push updates |

### Explicitly out of scope for v1

- No history/analytics tools beyond `get_history` (no P&L breakdowns, no chart data — agents can compute from `get_history`)
- No backtesting, no strategy templates, no signal generation
- No multi-account management — one MT5 terminal at a time
- No automation primitives ("place this order in 5 minutes" — agent runtime's job, not MCP's)
- No copy-trading / social features
- No symbol watchlists / favourites — read-only `get_symbols` is enough

---

## 6. Type system

All tools return Pydantic models serialised to JSON. Concrete shapes (illustrative — full schemas in `docs/tools.md`):

```python
class AccountInfo(BaseModel):
    login: int
    name: str
    server: str           # MT5 server name, e.g. "FintrixMarkets-Live"
    currency: str         # ISO 4217, e.g. "USD"
    balance: Decimal      # NOT float
    equity: Decimal
    margin: Decimal
    margin_free: Decimal
    margin_level: Decimal | None
    leverage: int
    trade_allowed: bool
    margin_mode: Literal["retail_netting", "exchange", "retail_hedging"]

class Position(BaseModel):
    ticket: int
    symbol: str
    type: Literal["buy", "sell"]
    volume: Decimal       # in lots
    price_open: Decimal
    price_current: Decimal
    sl: Decimal | None
    tp: Decimal | None
    profit: Decimal
    swap: Decimal
    commission: Decimal
    time_open: datetime   # timezone-aware
    comment: str | None

class OrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    volume: Decimal
    type: Literal["market", "limit", "stop", "stop_limit"]
    price: Decimal | None         # required for limit/stop
    sl: Decimal | None
    tp: Decimal | None
    deviation: int = 10           # max slippage in points
    comment: str | None
    idempotency_key: str | None   # client-supplied; see §8

class OrderResult(BaseModel):
    success: bool
    ticket: int | None
    symbol: str
    type: str
    volume: Decimal
    price_filled: Decimal | None
    requested: OrderRequest
    error: ErrorDetail | None
    server_response_code: int     # mt5lib retcode
```

**Conventions:**
- All money / prices / volumes are `Decimal`, serialised to JSON as strings (`"100.50"`)
- All timestamps are timezone-aware `datetime`, serialised as ISO 8601 with offset
- All enum-like fields are string literals (lowercase, snake_case)
- Errors use a structured `ErrorDetail` model with `code`, `message`, `retryable: bool`, `details: dict`

---

## 7. Configuration

Single config file: `~/.config/mt5-mcp/config.toml` (or `%APPDATA%\mt5-mcp\config.toml` on Windows). Loaded at server start, hot-reloaded on SIGHUP.

```toml
[mt5]
# Path to MT5 terminal executable. Auto-detected if omitted.
terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

# Login is read from the running terminal; not configured here.
# If multiple terminals are running, specify by login:
# preferred_login = 12345678

[policy]
# Auto-approve trades at or below this notional in account currency.
# Above this, the tool returns requires_approval and the agent must
# obtain explicit consent (e.g. via 1Password biometric).
auto_approve_notional = "1000.00"

# Hard local cap. Trades above this are refused outright by mt5-mcp,
# regardless of consent. Server-side limits still apply on top.
max_notional_per_trade = "10000.00"

# Refuse close_position requests that would realise a loss above this.
max_realised_loss_per_close = "500.00"

# Refuse new orders that would push total daily realised loss above this.
max_daily_loss = "2000.00"

[idempotency]
# Idempotency keys are remembered for this duration. Replays within
# the window return the original result.
ttl_seconds = 86400  # 24h

[symbols]
# Optional allowlist. If non-empty, only listed symbols can be traded.
allowlist = []  # e.g. ["EURUSD", "GBPUSD", "XAUUSD"]

# Optional denylist. Trades on these symbols are refused.
denylist = []

[audit]
# Append-only JSONL log of every tool call.
path = "~/.local/share/mt5-mcp/audit.jsonl"

# Rotate when the file exceeds this size.
max_bytes = 10_485_760  # 10 MB

[telemetry]
# Off by default. If enabled, sends anonymous usage stats (tool name +
# success/error count, no payloads) to the configured endpoint.
enabled = false
endpoint = ""

[transport.http]
# Only applies when running serve --transport http.
port = 8765
auth_token = ""  # optional bearer token; leave empty to disable auth

[streaming]
# Background poll cadences for MCP resource subscriptions.
# Clients that subscribe receive notifications/resources/updated on change.
quote_poll_ms = 200    # quotes://{symbol} — bid/ask diff
account_poll_ms = 1000 # account://current and positions://current
```

**Config validation:** Pydantic model. Server refuses to start with an invalid config and prints a clear error.

---

## 8. Policy engine

### 8.1 Consent gate

Mutating tools emit `requires_approval` when the request exceeds `policy.auto_approve_notional`. The MCP returns a structured `ApprovalPreview` — the agent obtains consent (e.g. via 1Password biometric in OpenClaw), then retries with `approval_confirmed: true` and the same `approval_request_id`.

```python
# Returned when over auto-approve threshold:
{
  "request_id": "01HX...",
  "expires_at": "2026-04-21T10:35:00Z",
  "summary": "BUY 0.5 EURUSD @ market (~$54000 USD)",
  "action": "place_order",
  "symbol": "EURUSD",
  "notional": "54000.00",
  "estimated_margin": "540.00",
  "reference_quote": {"symbol": "EURUSD", "bid": "1.0823", "ask": "1.0824",
                      "time": "2026-04-21T10:30:00Z"},
  "request_echo": {...}
}

# Agent retries with approval_confirmed:
{
  "tool": "place_order",
  "arguments": {
    ...,
    "approval_confirmed": true,
    "approval_request_id": "01HX..."
  }
}
```

**The consent gate is a UX/policy affordance, not a cryptographic control.** Real authentication lives at the transport layer — the OS process boundary for stdio, Tailscale's WireGuard node identity for HTTP. The MCP only verifies:

- The `approval_request_id` matches a stored, un-expired preview.
- The retry's identical fields (action / symbol / side / type / volume / ticket) match the preview.
- The retry's price is within `max(0.5%, deviation_points × point)` of the stored `reference_quote`.

On mismatch the MCP returns `INVALID_APPROVAL`. This protects against prompt-injection "bait and switch" attacks where an agent might trick a human into approving trade A but submit trade B.

Agent runtimes are free to layer additional authentication (biometrics, multi-person approval, hardware tokens) on top of the simple flag.

### 8.2 Pre-flight limits

**These are not security controls.** The broker's MT5 server enforces per-trade, per-account, and leverage limits server-side; any trade exceeding broker limits gets rejected there regardless of what the MCP allows.

The MCP's pre-flight checks exist for UX: catching obviously invalid trades locally (~1 ms) gives the agent immediate feedback instead of a ~200 ms round-trip to a `REJECTED_BY_SERVER`.

Hard refusals (no `approval_confirmed` overrides these):

- `volume * price > policy.max_notional_per_trade`
- Symbol in `symbols.denylist`
- Symbol not in `symbols.allowlist` (when allowlist is non-empty)
- Daily realised P&L would breach `policy.max_daily_loss` (place_order only)
- Realised loss on close > `policy.max_realised_loss_per_close` (close_position only)

The daily P&L day boundary is **broker-server-day** — derived from the cached `broker_offset_minutes` set at `MT5Client.connect()`. P&L is `sum(deal.profit + deal.swap + deal.commission)` over `mt5.history_deals_get(broker_day_start, broker_now)`.

### 8.3 Idempotency

Every mutating tool accepts an optional `idempotency_key`. If supplied:

- First call with this key executes normally; the resulting `OrderResult` is cached.
- Subsequent calls with the same key AND same canonical request hash within `idempotency.ttl_seconds` return the cached result with `replayed: true`.
- Same key, **different** request hash → `IDEMPOTENCY_DIVERGED` error. This surfaces caller bugs (e.g. forgetting to vary the key between distinct trades) instead of silently masking them.

Stored in a small SQLite database at `<user_data>/idempotency.db` (per-OS path via `platformdirs`; overridable in `config.toml` under `[idempotency] path`).

Without a key, no caching; agents are encouraged to supply UUIDv4s. Without one, retries after a network timeout could double-execute.

### 8.4 Audit log

Every tool call appends one JSONL line to `<user_data>/audit.jsonl` (per-OS path via `platformdirs`; overridable in `config.toml` under `[audit] path`).

```json
{"ts": "2026-04-26T10:30:00Z", "tool": "place_order", "action": "executed",
 "request": {...}, "result_status": "filled", "ticket": 12345,
 "duration_ms": 142, "approval_request_id": null,
 "idempotency_key": "01HX...", "request_hash": "sha256:..."}
```

`action` is one of: `executed`, `requires_approval`, `replay`, `preflight_refused`, `invalid_approval`, `idempotency_diverged`, `error`, `called` (read-only tools log only this).

Mutating-tool events log the full request and result. Read-only events log only the call shape — result bodies would dominate disk on tight loops.

Rotation: when `os.path.getsize(audit.path) > audit.max_bytes`, the file is renamed to `audit.jsonl.<unix_epoch>` and a fresh handle opened. No compression; rotated files persist on disk indefinitely (operator's choice when to archive).

Customer can `tail -f` (`Get-Content -Wait` on Windows) the audit log to watch their agent in real time. Useful for debugging and for compliance reviews.

---

## 9. Transports

### 9.1 stdio (v1, default)

The server reads JSON-RPC messages from stdin and writes responses to stdout. Standard MCP transport, supported by Claude Desktop, OpenClaw, Cursor, every reference MCP client.

Launched by the agent runtime as a subprocess:

```json
// Claude Desktop config snippet (~/Library/Application Support/Claude/config.json)
{
  "mcpServers": {
    "mt5": {
      "command": "python",
      "args": ["-m", "mt5_mcp"],
      "env": {
        "MT5_MCP_CONFIG": "/Users/jane/.config/mt5-mcp/config.toml"
      }
    }
  }
}
```

### 9.2 HTTP (v0.3, optional)

For agent runtimes that prefer a persistent HTTP endpoint over a managed subprocess. Spawned as a long-running server:

```bash
python -m mt5_mcp serve --transport http
```

Port and auth token come from `config.toml`:

```toml
[transport.http]
port = 8765
auth_token = ""  # optional bearer token; leave empty to disable auth
```

**Loopback-only in v0.3.** The server binds to `127.0.0.1` (and `::1` / `localhost`). Attempting to bind any other address raises `ConfigError` at startup. Phase 4 may lift this if a customer asks for a LAN-accessible deployment.

**Optional bearer-token auth.** When `transport.http.auth_token` is non-empty, every incoming request must carry `Authorization: Bearer <token>`. The comparison is constant-time (`hmac.compare_digest`) to resist timing attacks. Setting `auth_token = ""` disables auth entirely (suitable when the caller is already bound to loopback and the OS provides process-level isolation).

**Underlying transport.** FastMCP's `streamable-http` transport handles both request/response and SSE streaming on the same endpoint. Port and host are configured by mutating `mcp.settings.host` / `mcp.settings.port` before calling `mcp.run(transport="streamable-http")` — FastMCP 3.x does not accept these as `run()` kwargs.

See §18 for the full HTTP transport design notes.

HTTP transport is documented as an opt-in feature, not the primary path. Most users should stay on stdio.

---

## 10. Connection lifecycle

```
1. Agent runtime spawns mt5-mcp (stdio)
2. mt5-mcp loads config
3. mt5-mcp calls mt5lib.initialize()
   - If terminal_path is set in config, uses it
   - Otherwise auto-discovers
   - Returns False if no terminal running or login is stale
4. On initialize failure:
   - mt5-mcp returns a clear error on the first tool call:
     "MT5 terminal not connected. Please open MT5 and log into your broker."
   - Server keeps running; agent can retry after the human fixes it
5. On initialize success:
   - mt5-mcp registers all tools
   - Agent calls tools normally
6. Agent runtime closes the subprocess (SIGTERM or stdin close)
7. mt5-mcp calls mt5lib.shutdown() and exits cleanly
```

**Connection health:** `ping` tool verifies `mt5.terminal_info()` returns non-None. Returns latency. Agents should ping after long idle periods or after errors that smell like connection loss.

**Reconnection:** If `mt5lib` returns "not initialized" mid-session, mt5-mcp transparently calls `initialize()` once and retries the underlying call. If reinit fails, returns a structured error.

---

## 11. Error handling

All errors returned to the agent are structured, never raw Python exceptions.

```python
class ErrorDetail(BaseModel):
    code: str                     # machine-readable, e.g. "TERMINAL_NOT_CONNECTED"
    message: str                  # human-readable, e.g. "MT5 terminal is not connected. Please open MT5."
    retryable: bool               # whether the agent should retry without human intervention
    requires_human: bool          # whether the agent should escalate to the human
    details: dict | None          # error-specific structured data
    mt5_retcode: int | None       # original mt5lib retcode if applicable
```

### Standard error codes (illustrative — full list in `docs/tools.md`)

| Code | Meaning | retryable | requires_human |
|---|---|---|---|
| `TERMINAL_NOT_CONNECTED` | MT5 isn't running or logged in | false | true |
| `TRADE_DISABLED` | Trading disabled on the account | false | true |
| `MARKET_CLOSED` | Symbol's session is closed | false | false |
| `SYMBOL_NOT_FOUND` | Symbol doesn't exist on this broker | false | false |
| `SYMBOL_NOT_ENABLED` | Symbol exists but trading disabled (e.g. weekend on crypto pair) | true | false |
| `INSUFFICIENT_MARGIN` | Not enough free margin for this trade | false | true |
| `INVALID_VOLUME` | Volume doesn't satisfy symbol's lot step / min / max | false | false |
| `INVALID_PRICE` | Price too far from market or invalid for order type | true | false |
| `REQUOTE` | Price moved during execution; try again | true | false |
| `REJECTED_BY_SERVER` | Broker server rejected for unspecified reason | false | true |
| `EXCEEDS_LOCAL_LIMIT` | Hit a soft limit configured in mt5-mcp | false | true |
| `REQUIRES_APPROVAL` | Above auto-approve threshold; consent needed | false | true |
| `INVALID_APPROVAL` | Approval token invalid or expired | false | true |
| `IDEMPOTENCY_REPLAY` | Returning cached result for an earlier call | false | false |

mt5lib's full retcode table is mapped in `adapter/mt5_client.py`. Unknown retcodes surface as `MT5_UNKNOWN_RETCODE` with the raw code in `details`.

---

## 12. Security & threat model

### 12.1 What mt5-mcp protects

- **The audit log is append-only** — agents can't suppress evidence of their own actions
- **Hard local limits** prevent runaway trades from a misbehaving agent
- **Idempotency keys** prevent duplicate execution from network retries
- **Approval tokens** are scoped to a single request and time-bound
- **Read tools log only call shape**, not full payloads — limits leak risk if the audit log is exfiltrated

### 12.2 What mt5-mcp does NOT protect

- **A compromised customer machine.** Anyone with shell access can read the MT5 terminal's session, modify the config, or read the audit log. The MCP can't defend against this; it's the customer's responsibility.
- **A malicious agent runtime.** If OpenClaw or whatever is running the show is compromised, the MCP will dutifully execute trades it sends. The server-side broker limits are the real backstop.
- **Stolen credentials.** The MCP doesn't see the customer's login credentials — they're in the terminal already. But if those creds leak elsewhere, a separate attacker can log in and trade. That's the broker's problem.

### 12.3 Network exposure

- **Default: zero network surface.** stdio transport, no listening sockets.
- **HTTP transport opt-in only**, default-binds to localhost.
- **No telemetry by default.** Opt-in via config.
- **No auto-update.** Customer chooses when to `pip install -U mt5-mcp`. We won't pull code at runtime.

### 12.4 Disclosure

`SECURITY.md` describes the disclosure process and contact (`security@fintrixmarkets.com` for the launch; ideally a separate `security@mt5-mcp.dev` once the project has its own domain).

---

## 13. Testing strategy

Three layers:

**1. Unit tests (`tests/`).** Mock `mt5lib` entirely. Cover the adapter, conversions, policy engine, idempotency store, and audit log. Run on every commit. Target ≥90% coverage on `src/mt5_mcp/policy/` and `src/mt5_mcp/adapter/`.

**2. Integration tests (`tests/integration/`).** Run against a real MT5 terminal connected to a broker demo account. Not run in CI by default — requires Windows + MT5 install + broker creds. Documented in `tests/integration/README.md` for contributors to run locally.

**3. Smoke test (CLI).**
```bash
python -m mt5_mcp doctor
```
Connects to the terminal, runs through every tool's read path, prints a green/red health report. Customers run this after install. If `doctor` is green, the MCP is ready.

---

## 14. Distribution & versioning

- **PyPI:** `pip install mt5-mcp`. Wheel includes everything; no native deps beyond `MetaTrader5` itself.
- **Source:** GitHub, MIT licensed.
- **Releases:** SemVer. Breaking changes only on major bumps. Tool surface is stable from v1.0.
- **Python support:** 3.10+ (matches `MetaTrader5` library's minimum).
- **Platform support:** Windows is first-class. WSL2 + Wine paths documented but not first-class. Mac/Linux native is not supported until MetaQuotes ships a cross-platform `MetaTrader5`.

---

## 15. What gets built when

Suggested implementation order for Claude Code. Each phase ships independently and can be tested in isolation.

**Phase 1 — Skeleton + read tools (1 week)**
- `pyproject.toml`, package layout, MIT licence, basic `README.md`
- Config loader with Pydantic
- `adapter/mt5_client.py` — singleton wrapper around `mt5lib`
- `adapter/conversions.py` — type marshalling
- All 9 read tools wired to `mt5lib`
- Unit tests for adapter + conversions
- `doctor` smoke command

**Phase 2 — Mutating tools + policy (1 week)**
- `place_order`, `modify_order`, `close_position`, `cancel_order`
- Policy engine (consent gate, soft limits, idempotency, audit log)
- Approval token verification
- Unit tests for policy + tools
- Integration test for happy-path order placement against demo broker

**Phase 3 — Resources + transports (3 days)** ✅ complete
- `account://current`, `positions://current`, `quotes://{symbol}` resources
- HTTP transport behind a CLI flag (`serve --transport http`), loopback-only
- Shared Poller + Dispatcher streaming subsystem; see §17
- Plugin loader for third-party tools moved to Phase 4

**Phase 4 — Polish (3 days)**
- `docs/` site auto-generated from docstrings
- Example client configs (Claude Desktop, OpenClaw, Cursor)
- `SECURITY.md` + threat model
- Plugin loader for third-party tools (moved from Phase 3)
- v1.0 release on PyPI
- GitHub repo public + announcement

**Total: ~3 weeks.** Realistic for one engineer working on this full-time.

---

## 16. Open questions for review

1. **Repo home.** `github.com/fintrixmarkets/mt5-mcp` ties identity to one broker. `github.com/mt5-mcp/mt5-mcp` is more neutral but requires registering the org now. Recommend the latter — pays off for adoption.
2. **Approval token format.** HMAC-signed JWT-like blob is straightforward but specifying a format pre-emptively constrains agent runtimes. Alternative: leave the format to the runtime and have mt5-mcp call out to a verifier callback. Less elegant, more flexible.
3. **History tool depth.** `get_history` could return either deals (closed transactions) or orders (filled + cancelled). Most agents want deals for P&L analysis. Ship deals only in v1; add `get_orders_history` if asked for.
4. **Quote subscriptions.** ✅ Resolved. `quotes://{symbol}` is backed by a single shared Poller that polls `get_quote` at a configurable cadence (default 200 ms). Multiple subscriptions to different symbols each run through the same poller loop; the Dispatcher fans out change notifications per URI. Poll cadence is configurable via `[streaming] quote_poll_ms` in `config.toml`. See §17 for the full streaming subsystem design.
5. **Symbol name normalisation.** Brokers use different naming conventions (`EURUSD`, `EURUSD.r`, `EURUSDm`, `EUR/USD`). v1 passes the customer's exact symbol string through to `mt5lib`. v2 could add a normaliser. Don't try to be clever in v1.
6. **Multi-account support.** The `MetaTrader5` Python library supports one terminal per process. Multi-account would require launching multiple MCP processes. Not a v1 feature; document the limitation.
7. **Audit log encryption.** Plaintext JSONL is reviewable but not encrypted. For customers who care, document how to symlink the audit file to an encrypted volume. Don't build encryption in.
8. **Telemetry.** Opt-in only is the right default. But should we accept anonymous tool-name + success/failure counts to understand which tools matter most? Useful for prioritising v2; risk is even opt-in telemetry erodes the local-first claim. Recommend: ship with telemetry stubbed out, add later if there's demand.

---

---

## 17. Streaming subsystem (Phase 3)

The streaming subsystem drives MCP resource subscriptions for `account://current`, `positions://current`, and `quotes://{symbol}`.

### 17.1 Components

**`Poller` (`src/mt5_mcp/streaming/poller.py`)** — a single background daemon thread that runs a tight poll loop. On each cycle it:

1. Fetches the current snapshot for every registered URI from the MT5 adapter.
2. Compares the snapshot to the previous one using the URI-specific diff rule (see §17.2).
3. If a change is detected, calls `dispatcher.dispatch(uri, new_snapshot)`.
4. Calls `dispatcher.reap_dead_subscribers()` — this is the only mechanism that removes subscriptions from dead HTTP sessions.

The poller is lazy-started: it does not run until the first `dispatcher.subscribe(uri, callback)` call. It stops (daemon thread exits on next loop iteration) when the last subscriber unsubscribes.

**`Dispatcher` (`src/mt5_mcp/streaming/dispatcher.py`)** — holds the subscriber registry and fans out notifications. Each subscriber is a `(uri, callback)` pair. Fanout is sequential and synchronous within the poll cycle; callbacks must not block. The `FastMCPSubscriber` adapter (registered via `mcp._mcp_server.subscribe_resource()`) bridges the Poller's daemon thread to the FastMCP asyncio event loop via `asyncio.run_coroutine_threadsafe`.

**`snapshots.py` (`src/mt5_mcp/streaming/snapshots.py`)** — frozen dataclasses used as snapshot tokens. These live in production code, not in `tests/fakes.py`. Production MUST NOT import snapshot types from the test tree.

### 17.2 Change-detection rules

| Resource | Rule |
|---|---|
| `account://current` | Structural equality of the account snapshot, excluding floating P&L fields (`equity`, `margin`, `margin_free`, `margin_level`). Only balance-sheet changes (`balance`, `credit`, `leverage`, `trade_allowed`) trigger a notification. |
| `positions://current` | Set of (ticket, symbol, type, volume, price_open, sl, tp). Floating P&L (`profit`, `swap`) deliberately excluded. Notifications fire on position open/close or SL/TP modification — not on continuous mark-to-market. |
| `quotes://{symbol}` | Full bid/ask snapshot. Any price change triggers a notification. |

The deliberate exclusion of floating P&L from account and positions change-detection is a design choice, not a bug. Without this exclusion, every 200 ms tick would wake every subscribed client — generating noise with no actionable signal.

### 17.3 Lifecycle

```
subscribe(uri, cb)     → if first subscriber: start Poller thread
unsubscribe(uri, cb)   → if last subscriber: set Poller._stop flag
reap_dead_subscribers  → called by Poller each cycle; removes callbacks that raise on invocation
```

The Poller thread is a `threading.Thread(daemon=True)`. It will not prevent process exit. HTTP-session-detached subscriptions are reaped on the next dispatch cycle after their callback raises.

### 17.4 AppContext integration

`AppContext` gains two new fields:

```python
dispatcher: Dispatcher   # always present after build_server()
poller: Poller           # always present; started lazily on first subscribe
```

Resources call `ctx.dispatcher.subscribe(uri, cb)` / `ctx.dispatcher.unsubscribe(uri, cb)` directly. They do not interact with the Poller directly.

---

## 18. HTTP transport design notes (Phase 3)

### 18.1 Loopback constraint

The server calls `socket.getaddrinfo(host, None)` on the configured `host` and rejects any address that does not resolve to a loopback address (`127.x.x.x` for IPv4, `::1` for IPv6). This check runs at startup before `mcp.run()`. The error message is explicit: "HTTP transport only binds to loopback addresses in v0.3. Use stdio for remote deployments."

### 18.2 Bearer-token middleware

When `transport.http.auth_token` is non-empty, a Starlette middleware intercepts every request before routing. It extracts the `Authorization` header, compares the token via `hmac.compare_digest`, and returns `401 Unauthorized` on mismatch. The comparison is constant-time to prevent timing-oracle attacks.

The token is never logged. Server startup prints: "HTTP transport: bearer-token auth enabled" (no token value).

### 18.3 FastMCP settings mutation

FastMCP 3.x's `mcp.run()` does not accept `host` or `port` keyword arguments for the `streamable-http` transport. The transport module sets them on `mcp.settings` before calling `run()`:

```python
mcp.settings.host = resolved_host   # e.g. "127.0.0.1"
mcp.settings.port = cfg.transport.http.port
mcp.run(transport="streamable-http")
```

This pattern is fragile against FastMCP version upgrades. If a future FastMCP release changes how settings are applied, the transport module is the single place to update.

### 18.4 Subscribe hooks

FastMCP does not expose resource subscribe/unsubscribe hooks at its high-level surface. The low-level `mcp._mcp_server` (`mcp.server.Server`) does. `FastMCPSubscriber` registers handlers via:

```python
mcp._mcp_server.subscribe_resource(uri_str, on_subscribe)
mcp._mcp_server.unsubscribe_resource(uri_str, on_unsubscribe)
```

The subscribe callback calls `ctx.dispatcher.subscribe(uri, cb)` where `cb` is a coroutine that calls `mcp._mcp_server.request_context.session.send_resource_updated(uri)`. The `asyncio.run_coroutine_threadsafe` bridge is necessary because the Dispatcher's fanout runs in the Poller daemon thread, not in the asyncio event loop.

---

*End of architecture document. Hand to Claude Code with the implementation order from §15 to begin.*
