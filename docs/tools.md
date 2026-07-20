# Tools & resources

[<- Back to README](../README.md)

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
| `get_chart_screenshot(symbol, timeframe, annotations?)` | PNG of the native MT5 chart, optionally annotated (Windows only; needs the AgentScreenshot EA). |
| `calc_margin(symbol, side, volume, price?)` | Broker-authoritative margin estimate for a hypothetical order. |

### Chart annotations

`get_chart_screenshot` takes an optional `annotations` list (max 16) that marks
up the chart before capture.

| Type | Anchors | Use |
|---|---|---|
| `hline` | `price` | Support/resistance level across the chart; `text` optional. |
| `vline` | `time` | Time marker, e.g. a news release; `text` optional. |
| `text` | `time`, `price` | Note placed freely against price action; `text` required. |
| `label` | `corner` | Note pinned to a chart corner, no coordinates needed; `text` required. |
| `trendline` | `time1/price1`, `time2/price2` | Diagonal support/resistance; `text` optional. |

`role` sets the color and style: `resistance` (firebrick), `support` (navy),
`note` (darkslate, default), `neutral` (dimgray dashed). These defaults are
tuned for MT5's light chart template. Set `color` to override it (`red`,
`lime`, `yellow`, `gray`, `white`, `aqua`, `orange`, `magenta`, `firebrick`,
`navy`, `darkslate`, `dimgray`) - the brighter names suit a dark template.
`text` is up to 128 characters; required on `text` and `label`, optional on
the rest.

```json
[
  {"type": "hline", "price": 2650.0, "role": "resistance", "text": "daily R"},
  {"type": "text", "time": "2026-07-19T12:00:00Z", "price": 2612.0,
   "text": "failed breakout"},
  {"type": "label", "corner": "top_left", "text": "range-bound, low conviction"}
]
```

> Times are UTC and must come from real bar timestamps (`get_rates`), not
> guesses, or the annotation lands off-screen. Prices outside the visible price
> range and times older than the visible window are accepted but will not
> appear either, since the capture shows roughly the most recent screen of
> bars. Annotations are drawn on the temporary chart the capture already
> opens, so they are destroyed with it and never appear on your own charts.

> Avoid anchoring a `text` annotation to the last few bars at the same price as
> an `hline`. MT5 pins the hline's own description to the right margin, so the
> two overlap and both become unreadable - offset the text a few bars back,
> shift its price, or drop the hline's `text`. The temporary chart also
> inherits your default template, so template indicators appear in the capture
> alongside the annotations; point `[screenshot] template` at a clean `.tpl` if
> you want them out.

## Mutating tools (preflight + consent + idempotency + audit)

| Tool | Purpose | Gate |
|---|---|---|
| `place_order` | Market or pending order with optional SL/TP/deviation. | When armed: notional ≥ `auto_approve_notional` -> `ApprovalPreview`. |
| `modify_order` | Change SL/TP/expiry on a position or pending order. | When armed: widening or removing SL/TP on a position -> `ApprovalPreview`. Tightening auto-approves. |
| `close_position` | Close a position by ticket, in full or part. | When armed: notional ≥ `auto_approve_notional` -> `ApprovalPreview`. |
| `cancel_order` | Cancel a pending order by ticket. | Never gates (reduces exposure). |

> **The gate is opt-in and off by default.** `auto_approve_notional` defaults to
> `0`, so out of the box mutating calls auto-execute (full-open). Set it > 0 (see
> [Configuration](configuration.md)) to arm the gate: orders/closes at or above
> that notional then require human approval, and widening a stop does too.

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
