# Tools & resources

[← Back to README](../README.md)

`mt5-mcp` exposes the MetaTrader 5 terminal as a set of MCP tools and
subscribable resources.

## Read-only tools (no consent gate)

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
| `get_rates(symbol, timeframe, count)` | OHLC bars (M1…MN1), most recent first. |
| `calc_margin(symbol, side, volume, price?)` | Broker-authoritative margin estimate for a hypothetical order. |

## Mutating tools (preflight + consent + idempotency + audit)

| Tool | Purpose | Gate |
|---|---|---|
| `place_order` | Market or pending order with optional SL/TP/deviation. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `modify_order` | Change SL/TP/expiry on a position or pending order. | Widening or removing SL/TP on a position → `ApprovalPreview`. Tightening auto-approves. |
| `close_position` | Close a position by ticket, in full or part. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `cancel_order` | Cancel a pending order by ticket. | Never gates (reduces exposure). |

### Consent flow

When a tool returns an `ApprovalPreview`, the agent shows it to the human, then
retries the same call with `approval_confirmed=true` and the original
`approval_request_id`. The MCP validates the retry matches the preview (price
drift ≤ `max(0.5%, deviation × point)`, identical symbol/side/type/volume/ticket).
On mismatch the retry is refused as `INVALID_APPROVAL`.

### Idempotency

All mutating tools accept an optional `idempotency_key`; pass a UUIDv4 to dedupe
retries within `idempotency.ttl_seconds`.

## Resources (subscribable)

| URI | What it returns |
|---|---|
| `account://current` | Live account snapshot (balance, equity, margin, leverage, …). |
| `positions://current` | All open positions. |
| `quotes://{symbol}` | Current bid/ask for `symbol` (e.g. `quotes://EURUSD`). |

A subscribed client receives a `notifications/resources/updated` message when
the underlying data changes, then re-reads the resource to get the latest
snapshot. Floating P&L is excluded from the change-detection diff for
`account://` and `positions://` (subscribers are only woken on balance-sheet or
position-count changes); `quotes://{symbol}` notifies on any bid/ask change.
