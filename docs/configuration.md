# Configuration

[<- Back to README](../README.md)

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
auto_approve_notional = "1000.00"      # arm the consent gate: at or above this, place_order returns an ApprovalPreview (0 = default = gate off, orders auto-execute)
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
# Only relevant when using --transport http. Loopback-only.
port = 8765
auth_token = ""  # bearer token; EMPTY = unauthenticated (any local process can trade) - set one for HTTP
stateless = true # default; fresh transport per request - see "HTTP memory & logging" below

[streaming]
quote_poll_interval_ms = 200       # how often quotes://{symbol} checks for price changes
account_poll_interval_ms = 1000    # how often account://current is checked
positions_poll_interval_ms = 1000  # how often positions://current is checked

[logging]
level = "WARNING"  # WARNING (default) keeps an unattended server quiet; INFO / DEBUG for more
```

> **Defaults differ from this example.** Every guardrail above is **opt-in and
> off by default.** `auto_approve_notional` defaults to `0`, which means the
> consent gate is **off** - out of the box mutating calls auto-execute (full-open,
> for trusted/unattended agents). The `max_*` limits default to `0` and the symbol
> lists default to empty, which for them also means **off** (no local cap; the
> broker still enforces its own). The values above are a suggested hardened
> configuration; set `auto_approve_notional` > 0 to require human approval on
> orders at or above that notional.

## HTTP memory & logging

These matter for an unattended HTTP server (a VPS, the Docker image) where a
client polls tools around the clock.

- **`[transport.http] stateless`** (default `true`). In stateless mode the server
  builds a fresh transport per request and tears it down immediately. In stateful
  mode (`false`) it keeps one transport per MCP *session*, and the MCP SDK only
  frees it on a clean session close (HTTP `DELETE`). A client that opens a new
  session each poll and never closes it therefore leaks one transport per poll -
  the process grows unbounded. Keep `stateless = true` unless a client genuinely
  **subscribes** to resources for server-pushed updates (`quotes://`, `account://`,
  `positions://`); subscriptions need a persistent session and are inert in
  stateless mode (tools still work - clients just poll). Override per run with
  `serve --stateless` / `serve --no-stateless`.
- **`[logging] level`** (default `WARNING`). `WARNING` silences uvicorn's
  per-request access log and the SDK's per-request / transport-creation lines,
  while still surfacing the consent-posture and auth warnings. Use `INFO` for
  normal operational logging, `DEBUG` to trace everything (DEBUG also re-enables
  the per-request flood). Precedence: `serve --log-level` > `MT5_MCP_LOG_LEVEL`
  env > `[logging] level`.
- **Daily restart (Windows).** As a belt-and-suspenders against any residual
  growth, `examples/vps/install-mt5-mcp-task.ps1` installs a companion task that
  restarts the server once a day (default `03:30`); tune with `-DailyRestartAt`
  or skip with `-NoDailyRestart`.

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
