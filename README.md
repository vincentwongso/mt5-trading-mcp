# mt5-mcp

Model Context Protocol server wrapping the MetaTrader 5 Python library — exposes a logged-in MT5 terminal as a set of MCP tools an AI agent can call.

**Status:** v1.0 — first public release. Windows + Python 3.10+ required.

## Requirements

- Windows (the `MetaTrader5` Python library is Windows-only).
- Python 3.10 or newer.
- A running MetaTrader 5 terminal already logged into a broker.

## Install

From PyPI:

```bash
pip install mt5-trading-mcp
```

Or with [`uv`](https://docs.astral.sh/uv/):

```bash
uv pip install mt5-trading-mcp
```

> The PyPI distribution is `mt5-trading-mcp`, but the CLI command, Python module (`mt5_mcp`), and project brand are still `mt5-mcp`. The short name was already taken on PyPI by an unrelated project.

### From source (for contributors)

```bash
git clone https://github.com/vincentwongso/mt5-mcp.git
cd mt5-mcp
uv sync --extra dev
```

## Quick start

If you installed from source, activate the project virtualenv first so `python` resolves to the interpreter that has `mt5_mcp` installed:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bat
:: Windows cmd.exe
.\.venv\Scripts\activate.bat
```

```bash
# Git Bash / WSL on Windows
source .venv/Scripts/activate
```

Then:

```bash
# 1. Verify the MT5 terminal is reachable.
python -m mt5_mcp doctor

# 2. (Optional) Dump every tradeable symbol so you have a reference handy.
python -m mt5_mcp export-symbols --output symbols.csv

# 3. Run the server on stdio (default — what an MCP client invokes as a subprocess).
python -m mt5_mcp serve
```

To register the server with an MCP client, see the [example configs](https://github.com/vincentwongso/mt5-mcp/tree/main/examples/clients) — drop-in JSON snippets for Claude Desktop and Cursor.

## What it does

### Read-only tools (no consent gate)

| Tool | Purpose |
|---|---|
| `ping` | Health check; verifies the terminal is reachable. |
| `get_terminal_info` | Connection state, broker TZ offset, MT5 build. |
| `get_account_info` | Balance, equity, margin, leverage, currency. |
| `get_quote(symbol)` | Current bid/ask. |
| `get_symbols(category?)` | Tradeable instruments, optionally filtered. |
| `get_market_hours(symbol)` | Whether the symbol's session is open. |
| `get_positions(symbol?)` | Open positions. |
| `get_orders(symbol?)` | Pending orders. |
| `get_history(from_ts, to_ts, symbol?)` | Closed deals in a UTC range. |

### Mutating tools (preflight + consent + idempotency + audit)

| Tool | Purpose | Gate |
|---|---|---|
| `place_order` | Market or pending order with optional SL/TP/deviation. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `modify_order` | Change SL/TP/expiry on a position or pending order. | Widening or removing SL/TP on a position → `ApprovalPreview`. Tightening auto-approves. |
| `close_position` | Close a position by ticket, in full or part. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `cancel_order` | Cancel a pending order by ticket. | Never gates (reduces exposure). |

When a tool returns an `ApprovalPreview`, the agent shows it to the human, then retries the same call with `approval_confirmed=true` and the original `approval_request_id`. The MCP validates the retry matches the preview (price drift ≤ `max(0.5%, deviation × point)`, identical symbol/side/type/volume/ticket). On mismatch the retry is refused as `INVALID_APPROVAL`.

All mutating tools accept an optional `idempotency_key`; pass a UUIDv4 to dedupe retries within `idempotency.ttl_seconds`.

### Resources (subscribable)

| URI | What it returns |
|---|---|
| `account://current` | Live account snapshot (balance, equity, margin, leverage, …). |
| `positions://current` | All open positions. |
| `quotes://{symbol}` | Current bid/ask for `symbol` (e.g. `quotes://EURUSD`). |

A subscribed client receives a `notifications/resources/updated` message when the underlying data changes, then re-reads the resource to get the latest snapshot. Floating P&L is excluded from the change-detection diff for `account://` and `positions://` (subscribers are only woken on balance-sheet or position-count changes); `quotes://{symbol}` notifies on any bid/ask change.

## MCP client setup

Drop-in config snippets are in [`examples/clients/`](https://github.com/vincentwongso/mt5-mcp/tree/main/examples/clients):

- **Claude Desktop, stdio:** `examples/clients/claude-desktop-stdio.json`. Paste the inner `mcpServers` entry into `%APPDATA%\Claude\claude_desktop_config.json`.
- **Claude Desktop, HTTP:** `examples/clients/claude-desktop-http.json`. For when `mt5-mcp serve --transport http` is already running.
- **Cursor:** `examples/clients/cursor.json`. Paste into `~/.cursor/mcp.json`.
- **Claude Code:** clone this repo, then run `claude` from the repo root. Claude Code auto-discovers the `.mcp.json` at the project root and loads the project-scoped skills under `.claude/skills/` (`mt5-market-data` for read tools, `mt5-trading` for the consent flow). Read tools are pre-allowlisted in `.claude/settings.json`; mutating tools deliberately fire a permission prompt on every call. See [`Using with Claude Code`](#using-with-claude-code) below.

If `python` isn't on PATH (or you want to pin a specific venv), substitute the absolute path:

```json
{
  "mcpServers": {
    "mt5-mcp": {
      "command": "C:\\Users\\<you>\\.venvs\\mt5-mcp\\Scripts\\python.exe",
      "args": ["-m", "mt5_mcp", "serve"]
    }
  }
}
```

## Using with Claude Code

The repo ships with a project-scoped Claude Code setup so cloning is the entire install:

```
.mcp.json              # registers mt5-mcp on stdio
.claude/settings.json  # allowlists the nine read tools (mutating tools stay un-allowlisted)
.claude/skills/
├── mt5-market-data/SKILL.md   # what each read tool does + output conventions
└── mt5-trading/SKILL.md       # consent flow, idempotency, error taxonomy, demo framing
```

**To use:**

1. Clone the repo and install the package into the Python that Claude Code will spawn (`uv sync --extra dev` from the repo root, or `pip install mt5-trading-mcp` system-wide).
2. Launch the MT5 terminal and log into your broker.
3. From the repo root, run `claude`. Confirm `mt5-mcp` shows up under `/mcp`.
4. Ask the agent something like *"what's my account balance"* or *"show me the price of EURUSD"* — the read tools fire without a permission prompt; the `mt5-market-data` skill teaches the agent how to interpret the output.
5. Asking the agent to **place, modify, or close** a trade hits an interactive permission prompt (defence in depth above the policy engine's own consent flow). The `mt5-trading` skill walks the agent through preview → approval → execute.

If the spawned Python doesn't have `mt5_mcp` installed, edit `.mcp.json` to point at the right interpreter (e.g. `.venv\Scripts\python.exe`) — same shape as the snippet above.

## Configuration

Optional. Default config path:

- Windows: `%APPDATA%\mt5-mcp\config.toml`
- Linux/WSL: `$XDG_CONFIG_HOME/mt5-mcp/config.toml` (falls back to `~/.config/mt5-mcp/config.toml`)

The server starts with built-in defaults if the file is absent. Full schema documented in the [architecture spec, §7](https://github.com/vincentwongso/mt5-mcp/blob/main/mt5-mcp-architecture.md).

Minimal example:

```toml
[mt5]
terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

[policy]
auto_approve_notional = "1000.00"      # above this, place_order returns an ApprovalPreview
max_notional_per_trade = "10000.00"    # hard cap; no approval can override
max_realised_loss_per_close = "500.00" # close_position refuses if it would realise more
max_daily_loss = "2000.00"             # place_order refuses once daily realised loss hits this

[symbols]
allowlist = []  # if non-empty, only these symbols can be traded
denylist = []   # symbols here are always refused

[idempotency]
ttl_seconds = 86400  # 24h replay window for mutating tools that pass an idempotency_key

[transport.http]
# Only relevant when using --transport http. Loopback-only in v1.0.
port = 8765
auth_token = ""  # optional bearer token; leave empty to disable auth

[streaming]
quote_poll_interval_ms = 200       # how often quotes://{symbol} checks for price changes
account_poll_interval_ms = 1000    # how often account://current is checked
positions_poll_interval_ms = 1000  # how often positions://current is checked
```

The config file is hot-reloaded via `watchdog` whenever it changes on disk; broken edits are logged and ignored (the last-good config is retained). A running server can also be forced to reload immediately with `python -m mt5_mcp reload-config`.

**Storage paths** (idempotency DB and audit JSONL log) default to `platformdirs.user_data_dir("mt5-mcp", appauthor=False)`:

- Windows: `%LOCALAPPDATA%\mt5-mcp\{idempotency.db, audit.jsonl}`
- Linux/WSL: `~/.local/share/mt5-mcp/{idempotency.db, audit.jsonl}`

Both are overridable in `config.toml` under `[idempotency] path` and `[audit] path`.

## Transports

### stdio (default)

`python -m mt5_mcp` and `python -m mt5_mcp serve` both run in stdio mode. This is the correct choice for Claude Desktop, Cursor, and any agent runtime that manages the server as a subprocess.

### HTTP (opt-in)

For agent runtimes that prefer a long-running HTTP server instead of a subprocess:

```bash
python -m mt5_mcp serve --transport http
```

Constraints in v1.0:

- **Loopback-only** (`127.0.0.1`, `::1`, `localhost`). Binding to any other address raises a startup error. Direct LAN/internet exposure is intentionally not supported in v1.0; see the VPS deployment section below for the secure alternative.
- **Optional bearer-token authentication** via `transport.http.auth_token` in `config.toml`. When set, every request must carry `Authorization: Bearer <token>`. Comparison is constant-time.
- Uses the `streamable-http` FastMCP transport under the hood, which supports both request/response and SSE streaming on a single endpoint.

Default port: `8765` (configurable via `[transport.http] port`).

## Deploying to a Windows VPS

Common case: you want your MT5 terminal running 24/7 on a server, but laptops sleep. Two supported patterns:

### Pattern A — Agent + MCP both on the VPS

Simplest setup. RDP into the VPS, install Python and the MetaTrader 5 terminal, then:

```powershell
pip install mt5-trading-mcp
python -m mt5_mcp doctor   # verify the terminal is reachable
```

Run your MCP client (Claude Desktop, Cursor, or another) on the VPS itself and register `mt5-mcp` via the stdio config snippet. The agent's context lives on the VPS.

Practical notes:

- The MT5 terminal needs an active Windows desktop session to connect to the broker, so on an unattended VPS you'll want auto-logon configured at the OS level (your VPS provider's docs cover this) plus a Windows Task Scheduler trigger of "At log on" to launch MT5. "At system startup" alone won't work — MT5 needs a logged-in user.
- The `config.toml` watchdog hot-reload still works — just edit the file on the VPS.

### Pattern B — Agent local, MCP on the VPS via SSH tunnel

Use this when you want your agent running on your laptop but the MT5 terminal on the VPS.

On the VPS, run the HTTP transport (loopback-bound):

```powershell
python -m mt5_mcp serve --transport http
```

On your local machine, open an SSH tunnel that forwards the loopback port:

```bash
ssh -L 8765:localhost:8765 user@vps-host
```

Now `http://localhost:8765/mcp` on your laptop reaches the MCP on the VPS — without ever exposing the HTTP port to the public internet. Use the [`claude-desktop-http.json`](https://github.com/vincentwongso/mt5-mcp/tree/main/examples/clients/claude-desktop-http.json) example to register it with Claude Desktop.

This is the secure default for remote MT5 terminals. Direct non-loopback HTTP binding is intentionally **not** supported in v1.0 — it would require a TLS termination story and tighter auth than a single bearer token. If you need it for a real deployment, please open an issue describing the use case.

### Keeping `mt5-mcp serve` running

For Pattern A's HTTP transport or Pattern B's VPS-side server, you'll want the process to survive reboots:

- **NSSM** ([Non-Sucking Service Manager](https://nssm.cc/)) is the lightest option — wrap `python -m mt5_mcp serve --transport http` as a Windows Service.
- A scheduled task with "At system startup" + a restart-on-failure policy works too.

`mt5-mcp` doesn't bundle a service wrapper; pick the one your ops setup already uses.

## Safety

`mt5-mcp` is not the security boundary — the broker's MT5 server enforces hard limits (margin, max-lot, symbol permissions). Pre-flight checks in the policy engine are UX guardrails to catch agent mistakes early, not security controls.

Mutating actions above the configured `auto_approve_notional` (or that widen stops) require explicit human approval via the `ApprovalPreview` flow. Every mutating call is recorded in an append-only audit JSONL log.

For vulnerability disclosure, see [`SECURITY.md`](https://github.com/vincentwongso/mt5-mcp/blob/main/SECURITY.md).

## Development

Clone and sync:

```bash
git clone https://github.com/vincentwongso/mt5-mcp.git
cd mt5-mcp
uv sync --extra dev
```

Run the test suite (no live terminal required — uses `FakeMT5`):

```bash
uv run pytest -v
```

Run unit tests only (skip the integration test that starts a real HTTP server):

```bash
uv run pytest -m "not integration" -v
```

Live-terminal smoke checks (require a running MT5 terminal logged into a broker; the smoke-trade variant places a real micro-lot order — use a demo account):

```bash
python -m mt5_mcp doctor
python -m mt5_mcp doctor --smoke-trade
```

CI runs the unit-test suite on Windows runners across Python 3.10 / 3.11 / 3.12 on every push to `main` and every PR.

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

## Architecture

The full design is in [`mt5-mcp-architecture.md`](https://github.com/vincentwongso/mt5-mcp/blob/main/mt5-mcp-architecture.md). Phase implementation plans live under [`docs/superpowers/plans/`](https://github.com/vincentwongso/mt5-mcp/tree/main/docs/superpowers/plans).

## Licence

MIT — see [`LICENCE`](https://github.com/vincentwongso/mt5-mcp/blob/main/LICENCE).
