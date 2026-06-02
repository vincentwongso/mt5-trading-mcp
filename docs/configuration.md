# Configuration

[← Back to README](../README.md)

Configuration is optional - the server starts with built-in defaults if the
file is absent.

## Config file location

Default config path:

- Windows: `%APPDATA%\mt5-mcp\config.toml`
- Linux/WSL: `$XDG_CONFIG_HOME/mt5-mcp/config.toml` (falls back to
  `~/.config/mt5-mcp/config.toml`)

The full config schema is defined by the Pydantic models in
[`src/mt5_mcp/config.py`](../src/mt5_mcp/config.py).

## Minimal example

```toml
[mt5]
terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

[policy]
auto_approve_notional = "1000.00"      # at or above this, place_order returns an ApprovalPreview (0 = default = every order needs approval)
max_notional_per_trade = "10000.00"    # hard cap; no approval can override
max_realised_loss_per_close = "500.00" # close_position refuses if it would realise more
max_daily_loss = "2000.00"             # place_order refuses once daily realised loss hits this
max_orders_per_minute = 5              # 0 = no cap; throttles place_order to N orders/minute

[symbols]
allowlist = []  # if non-empty, only these symbols can be traded
denylist = []   # symbols here are always refused

[idempotency]
ttl_seconds = 86400  # 24h replay window for mutating tools that pass an idempotency_key

[transport.http]
# Only relevant when using --transport http. Loopback-only in v1.0.
port = 8765
auth_token = ""  # bearer token; EMPTY = unauthenticated (any local process can trade) - set one for HTTP

[streaming]
quote_poll_interval_ms = 200       # how often quotes://{symbol} checks for price changes
account_poll_interval_ms = 1000    # how often account://current is checked
positions_poll_interval_ms = 1000  # how often positions://current is checked
```

> **Defaults differ from this example.** `auto_approve_notional` defaults to `0`,
> which is **fail-closed** - out of the box *every* mutating call requires human
> approval. The `max_*` limits default to `0`, which for them means **off** (no
> local cap; the broker still enforces its own). The values above are a suggested
> configuration; raise `auto_approve_notional` to auto-approve orders below that
> notional.

## Hot reload

The config file is hot-reloaded via `watchdog` whenever it changes on disk;
broken edits are logged and ignored (the last-good config is retained). A
running server can also be forced to reload immediately with
`python -m mt5_mcp reload-config`.

## Storage paths

The idempotency DB and audit JSONL log default to
`platformdirs.user_data_dir("mt5-mcp", appauthor=False)`:

- Windows: `%LOCALAPPDATA%\mt5-mcp\{idempotency.db, audit.jsonl}`
- Linux/WSL: `~/.local/share/mt5-mcp/{idempotency.db, audit.jsonl}`

Both are overridable in `config.toml` under `[idempotency] path` and
`[audit] path`.
