# mt5-mcp

Model Context Protocol server wrapping the MetaTrader 5 Python library — exposes a logged-in MT5 terminal as a set of MCP tools an AI agent can call.

**Status:** v0.2, Phase 2 complete (skeleton + 9 read tools + 4 mutating tools + policy engine). Tag `phase-2-complete` at the most recent main. Phase 3 (Resources + HTTP transport) is the next milestone.

## Requirements

- Windows (the `MetaTrader5` Python library is Windows-only)
- Python 3.10+
- A running MetaTrader 5 terminal already logged into a broker

## Install

From source (recommended for now; not yet on PyPI):

```bash
git clone git@github.com:Fintrix-Markets/mt5-trading-mcp.git
cd mt5-trading-mcp
pip install -e ".[dev]"
```

Or with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

## Run

```bash
# Smoke check — runs every read tool against the live terminal
python -m mt5_mcp doctor

# Same plus a tiny live place_order + close_position round-trip
# (WARNING: places a real micro-lot order on the broker — demo accounts only)
python -m mt5_mcp doctor --smoke-trade

# Dump every tradeable symbol to CSV (run once per broker)
python -m mt5_mcp export-symbols --output symbols.csv

# Run the MCP server on stdio (default — what an MCP client invokes)
python -m mt5_mcp serve

# Force a config reload in a running server
python -m mt5_mcp reload-config
```

## Configuration

Optional. Default path:

- Windows: `%APPDATA%\mt5-mcp\config.toml`
- Linux/WSL: `$XDG_CONFIG_HOME/mt5-mcp/config.toml` (falls back to `~/.config/mt5-mcp/config.toml`)

The server starts with built-in defaults if the file is absent. See `mt5-mcp-architecture.md` §7 for the full schema.

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

[telemetry]
enabled = false
```

The config file is hot-reloaded via `watchdog` whenever it changes on disk; broken edits are logged and ignored (last-good config is retained).

**Storage paths** (idempotency DB and audit JSONL log) default to `platformdirs.user_data_dir("mt5-mcp", appauthor=False)`:
- Windows: `%LOCALAPPDATA%\mt5-mcp\{idempotency.db, audit.jsonl}`
- macOS: `~/Library/Application Support/mt5-mcp/{idempotency.db, audit.jsonl}`
- Linux: `~/.local/share/mt5-mcp/{idempotency.db, audit.jsonl}`

Both are overridable in `config.toml` under `[idempotency] path` and `[audit] path`.

## MCP client setup

Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mt5": {
      "command": "python",
      "args": ["-m", "mt5_mcp"]
    }
  }
}
```

Other MCP-compatible clients (Cursor, OpenClaw, etc.) use the same `python -m mt5_mcp` invocation as a stdio MCP server.

## Tools shipped in v0.2

### Read-only (no consent gate)

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

### Mutating (run through the policy engine: preflight + consent + idempotency + audit)

| Tool | Purpose | Gate |
|---|---|---|
| `place_order` | Market or pending order with optional SL/TP/deviation. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `modify_order` | Change SL/TP/expiry on a position or pending order. | Widening/removing SL or TP on a position → `ApprovalPreview`. Tightening auto-approves. |
| `close_position` | Close a position by ticket, in full or part. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `cancel_order` | Cancel a pending order by ticket. | Never gates (reduces exposure). |

When a tool returns an `ApprovalPreview`, the agent shows it to the human, then retries the same call with `approval_confirmed=true` and the original `approval_request_id`. The MCP validates the retry matches the preview within tolerance (price drift ≤ `max(0.5%, deviation × point)`, identical symbol/side/type/volume/ticket). On mismatch the retry is refused as `INVALID_APPROVAL`. The consent gate is a UX/policy affordance — real authentication lives at the transport layer (stdio process boundary; Tailscale node identity in Phase 3).

All mutating tools accept an optional `idempotency_key`; pass a UUIDv4 to dedupe retries within `idempotency.ttl_seconds`.

## Tests

```bash
pytest -v
```

176 unit tests run against a hand-rolled `FakeMT5` — no real terminal needed. The `doctor --smoke-trade` round-trip exercises `place_order` + `close_position` against a live demo broker.

## Architecture

Full design in [`mt5-mcp-architecture.md`](./mt5-mcp-architecture.md). Implementation plans:

- Phase 1 (skeleton + read tools): [`docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md`](./docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md)
- Phase 2 (mutating tools + policy engine): [`docs/superpowers/plans/2026-04-26-phase-2-mutating-tools-and-policy-engine.md`](./docs/superpowers/plans/2026-04-26-phase-2-mutating-tools-and-policy-engine.md) (spec: [`docs/superpowers/specs/2026-04-26-phase-2-mutating-tools-and-policy-engine-design.md`](./docs/superpowers/specs/2026-04-26-phase-2-mutating-tools-and-policy-engine-design.md))

## Licence

MIT.
