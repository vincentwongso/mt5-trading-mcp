# mt5-mcp

Model Context Protocol server wrapping the MetaTrader 5 Python library — exposes a logged-in MT5 terminal as a set of MCP tools an AI agent can call.

**Status:** v0.1, Phase 1 complete (skeleton + 9 read tools). Tag `phase-1-complete` at the most recent main.

## Requirements

- Windows (the `MetaTrader5` Python library is Windows-only)
- Python 3.10+
- A running MetaTrader 5 terminal already logged into a broker

## Install

From source (recommended for now; not yet on PyPI):

```bash
git clone git@github.com:Broker/mt5-trading-mcp.git
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

[symbols]
allowlist = []  # if non-empty, only these symbols can be traded (Phase 2)

[telemetry]
enabled = false
```

The config file is hot-reloaded via `watchdog` whenever it changes on disk; broken edits are logged and ignored (last-good config is retained).

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

## Tools shipped in v0.1 (read-only)

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

Mutating tools (`place_order`, `modify_order`, `close_position`, `cancel_order`) and the policy engine ship in Phase 2.

## Tests

```bash
pytest -v
```

89 unit tests run against a hand-rolled `FakeMT5` — no real terminal needed. Integration tests (a future addition) need a live demo broker.

## Architecture

Full design in [`mt5-mcp-architecture.md`](./mt5-mcp-architecture.md). Implementation plan in [`docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md`](./docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md).

## Licence

MIT.
