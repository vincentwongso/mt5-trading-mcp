---
name: mt5-market-data
description: Use when the user asks about their MetaTrader 5 broker account, balance, equity, margin, open positions, pending orders, trade history, current quotes / prices / bid-ask, tradeable symbols, OHLC bars / candles / chart data, chart screenshot / chart image / show me the chart, margin requirements for a hypothetical trade, market hours, or whether a symbol is currently tradeable. Triggers on questions like "what's my P&L", "show me my positions", "what's the price of EURUSD", "is the gold market open", "any pending orders on BTCUSD", "what trades did I do last week", "give me daily candles for XAUUSD", "what margin would 0.5 lot of US500 cost". Always use this skill before reaching for shell tools or web searches when the question is about MT5 broker state - the MCP has direct access.
---

# Reading MetaTrader 5 broker state

The `mt5-mcp` MCP server exposes twelve read-only tools and three resources that read live data from a running MetaTrader 5 terminal. Use them whenever the user wants to know the state of their account, market, or trading history. None of these tools mutate broker state - call them freely without confirmation.

## Tool catalogue

Each tool name below is the MCP tool name (Claude Code surfaces them as `mcp__mt5-mcp__<tool>`).

**`ping`** -> `{ok: bool, latency_ms: int}` - health check. Cheap; call this first if anything looks wrong (especially if a previous call returned `TERMINAL_NOT_CONNECTED`).

**`get_terminal_info`** -> broker server name, login, latency, broker timezone offset. Use when the user asks "what broker am I connected to" or you need to confirm the terminal is healthy before a sequence of reads.

**`get_account_info`** -> balance, equity, margin, free margin, leverage, currency, margin mode. Use for any question about account state, P&L (equity − balance ≈ floating P&L), or buying power.

**`get_quote(symbol)`** -> current `bid`, `ask`, `time` for one symbol. Use when the user asks about the current price, spread, or last tick. Symbols are auto-prepared in Market Watch on first use.

**`get_symbols(category=None)`** -> list of tradeable instruments with metadata. Each entry exposes:

- Identity: `name`, `description`, `category`, `digits`, `is_tradeable`, `filling_modes`
- Pricing: `tick_size` (price increment), `tick_value` / `tick_value_profit` / `tick_value_loss` (cash value of one tick in deposit currency), `contract_size`
- Volumes: `volume_min`, `volume_max`, `volume_step`
- Currencies: `currency_profit`, `currency_margin`
- **Calc dispatch:** `calc_mode` (string enum that drives which margin formula applies - `forex`, `cfd`, `cfd_index`, `cfd_leverage`, `forex_no_leverage`, `futures`, `exch_stocks`, etc.)
- **Margin:** `margin_initial`, `margin_maintenance`, `margin_hedged` (broker-set per-symbol values; typically zero for FX which uses contract_size/leverage)
- **Swaps:** `swap_long`, `swap_short`, `swap_mode` (string enum: `disabled`, `by_points`, `by_base_currency`, `by_margin_currency`, `by_deposit_currency`, `by_interest_current`, `by_interest_open`, `by_reopen_current`, `by_reopen_bid`), `triple_swap_weekday` (`sunday`..`saturday` - the day on which 3× rollover applies; commonly `wednesday` for FX, `friday` for some equity/index brokers)
- **Order-distance constraints:** `stops_level`, `freeze_level` (in points; multiply by `tick_size` for price distance)

Optionally filter by category like `"Forex"` or `"Metals"`. Use when the user wants to discover what they can trade, needs symbol metadata before placing an order, or needs swap rates / margin parameters / minimum SL distance.

**`get_rates(symbol, timeframe, count)`** -> list of OHLC bars, most recent first. `timeframe` is one of `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1`, `W1`, `MN1`. `count` is clamped to `[1, 5000]`. Each bar carries `time` (UTC), `open`, `high`, `low`, `close`, `tick_volume`, `real_volume`, `spread`. Use for indicator computation (ATR, RSI, EMA), volatility ranking, overbought/oversold detection - anything that needs price history rather than a single quote.

**`get_chart_screenshot(symbol, timeframe, annotations=None)`** -> PNG image of
the native MT5 chart for one symbol/timeframe. Windows-only (needs a GUI
terminal running the AgentScreenshot EA); returns `SCREENSHOT_NOT_SUPPORTED`
elsewhere. Prefer this when the user wants a visual read of price action or
support/resistance rather than raw numbers. `timeframe` is one of M1, M5, M15,
M30, H1, H4, D1, W1, MN1.

`annotations` (optional, max 16) marks up the chart before capture. Use it to
show the user *where* you see a level, not just to describe it - a drawn line
is far easier to check than a number in prose.

| type | anchors | required | optional |
|---|---|---|---|
| `hline` | `price` | - | `role, color, text` |
| `vline` | `time` | - | `role, color, text` |
| `text` | `time`, `price` | `text` | `role, color` |
| `label` | `corner` | `text` | `role, color` |
| `trendline` | `time1/price1`, `time2/price2` | - | `role, color, text` |

```json
[
  {"type": "hline", "price": 2650.0, "role": "resistance", "text": "daily R"},
  {"type": "text", "time": "2026-07-19T12:00:00Z", "price": 2612.0,
   "text": "failed breakout"},
  {"type": "label", "corner": "top_left", "text": "range-bound, low conviction"}
]
```

`role` picks the color and style: `resistance` (firebrick), `support` (navy),
`note` (dark slate, the default), `neutral` (dim gray, dashed). These defaults
are tuned for a light chart template; override with `color` (`red`, `lime`,
`yellow`, `gray`, `white`, `aqua`, `orange`, `magenta`, `firebrick`, `navy`,
`darkslate`, `dimgray`) if the user runs a dark one. Labels are capped at 128
characters. `corner` is `top_left` (default), `top_right`, `bottom_left` or
`bottom_right`; several labels in one corner stack automatically.

**Times must be real bar timestamps from `get_rates`, not guesses.** They are
UTC, same as everything else the server returns, and the conversion to broker
time happens server-side. Prices and times outside the visible window are
accepted but simply will not appear - the capture shows roughly the most recent
screen of bars, so annotate levels near current price. Nothing errors when an
annotation lands off-screen, so do not describe a level you have not confirmed
is actually in the returned image.

Markup is drawn on a temporary chart that is destroyed right after capture, so
it never touches the user's own charts and never needs clearing.

**`calc_margin(symbol, side, volume, price=None)`** -> broker-authoritative margin for a hypothetical order. Returns `{symbol, side, volume, price, margin, currency}` where `margin` is in deposit currency. If `price` is omitted, uses the current ask (buy) / bid (sell). Use this whenever the user asks "what would it cost to open X" - the broker's own answer is more reliable than any local formula because per-broker margin tables, hedged-position discounts, and exotic calc modes all factor in. Errors with `MARGIN_CALC_FAILED` if the broker refuses (e.g. invalid volume step, market closed, calc mode requires extra parameters).

**`get_market_hours(symbol)`** -> `{symbol, is_open, next_open, next_close}`. **v1 limitation: `next_open` and `next_close` are always `None`.** Only `is_open` (derived from broker `trade_mode`) is reliable. If the user wants precise session boundaries, point them at their broker's published schedule.

**`get_positions(symbol=None)`** -> list of open positions. Each carries ticket, symbol, side, volume, open price, current price, SL, TP, swap, profit, and open time. Use for "show me my positions" / "what am I holding" / "P&L per trade".

**`get_orders(symbol=None)`** -> list of pending orders (limit / stop / stop-limit). Distinct from positions - these haven't filled yet.

**`get_history(from_ts, to_ts, symbol=None)`** -> closed deals in the given UTC ISO 8601 range. Both timestamps must include a timezone (`Z` or `+00:00`); naive timestamps are rejected with `INVALID_TIMESTAMP`. Use for "what trades did I do yesterday / last week / since X".

## Resources

The server also exposes three subscribable MCP resources. Read them when the user wants a snapshot framed as "the current state of X" rather than "give me X":

- `account://current` - same shape as `get_account_info`. Subscribe for live equity/margin updates.
- `positions://current` - list of open positions. Subscribe to see opens / closes / SL-TP changes as they happen. **Floating P&L is not a change-detection trigger** - the resource only re-pushes when something structural changes (open, close, ticket attribute change), not on every tick.
- `quotes://{symbol}` - replace `{symbol}` with e.g. `quotes://EURUSD`. Subscribe for streaming bid/ask updates on that symbol.

For one-shot reads, prefer the equivalent tool - it's more obvious in transcripts. Subscribe to a resource only when the user genuinely wants a stream (e.g., "watch this" / "let me know when X").

## Output conventions

- **Timestamps are aware UTC.** All `time`, `time_setup`, `expiration`, etc. come back as ISO 8601 strings ending in `+00:00`. Convert to the user's local timezone in the response if it helps readability.
- **Decimals are stringified.** Prices, volumes, P&L, and limits are JSON strings (`"1.08512"`, `"0.10"`) so you don't lose precision through floats. When doing arithmetic, convert via `Decimal(...)` mentally / explicitly; never mix string-money with float-money.
- **Empty results are `[]`, not an error.** No positions, no pending orders, and no history matches all return an empty list.

## Errors

Tool failures arrive as MCP errors carrying a structured envelope: `{code, message, retryable, requires_human, details, mt5_retcode?}`. Common codes you'll see from read tools:

- `TERMINAL_NOT_CONNECTED` - operator hasn't launched MT5 or hasn't logged into the broker. Tell the user to open MT5 and log in, then retry.
- `SYMBOL_NOT_FOUND` - typo in symbol name. Suggest `get_symbols` to discover the right name.
- `SYMBOL_NOT_ENABLED` - symbol exists but has no tick data right now (market closed, broker maintenance). Often retryable later.
- `INVALID_TIMESTAMP` - `get_history` was called with naive or malformed timestamps. Always use `+00:00` or `Z`.
- `INVALID_TIMEFRAME` - `get_rates` was called with an unrecognised timeframe string. Use one of the documented values.
- `INVALID_COUNT` - `get_rates` was called with `count < 1`.
- `NO_RATES_AVAILABLE` - `get_rates` came back empty; the symbol may have insufficient history on this terminal. Often retryable later.
- `MARGIN_CALC_FAILED` - `calc_margin` was refused by the broker. Common causes: volume not a multiple of `volume_step`, market closed, calc mode that needs additional broker parameters.
- `INTERNAL_ERROR` - unexpected server-side exception. The full traceback is logged on the MCP server; the envelope only carries the exception type. Surface it cleanly to the user - don't retry blindly.
- `SCREENSHOT_NOT_SUPPORTED` - `get_chart_screenshot` called on a non-Windows host. (A Windows terminal that is down or missing the AgentScreenshot EA yields `SCREENSHOT_TIMEOUT` instead.)
- `SCREENSHOT_TIMEOUT` - the AgentScreenshot EA did not respond in time (not attached, or terminal down). Retryable.
- `SCREENSHOT_FAILED` - the EA could not open the chart or capture it (e.g. bad symbol). Retryable.
- `INVALID_ANNOTATION` - an `annotations` entry was malformed (unknown `role` / `color` / `corner`, non-finite price, empty or over-long `text`, `|` or a newline in `text`, or more than 16 entries). The whole call is rejected rather than the bad entry dropped, so nothing is captured. The message names the offending index. Not retryable without fixing the input.

## Workflow tips

1. **Diagnostic posture.** When the user reports something off ("why is my equity wrong?"), start with `ping` -> `get_terminal_info` -> `get_account_info` to confirm the connection and account state before drilling into specific symbols.
2. **One symbol vs all.** `get_positions(symbol="EURUSD")` is much cheaper than fetching all and filtering client-side. Use the optional symbol filter when you have one in hand.
3. **Prefer tools over resources for one-shot questions.** Resources shine for "watch this" requests; for "what's the price right now", `get_quote` is the right call.
4. **Don't compose your own broker schedules.** If the user wants "when does FX open Sunday night", consult their broker's website - `get_market_hours` only tells you whether it's open *now*.
5. **Draw the levels you claim to see.** When answering a support/resistance or pattern question, pull `get_rates` first, pick the levels off actual bar highs and lows, then pass them to `get_chart_screenshot` as `annotations` and read the returned image back. Quoting a number in prose asks the user to take your word for it; a drawn line lets them check it at a glance. Feed the bar `time` values straight through - they are already the UTC the annotation schema expects.

## See also

- `mt5-trading` skill - covers placing, modifying, cancelling, and closing orders. Loads automatically when the user wants to actually trade.
- `src/mt5_mcp/types.py` for the full data model (the Pydantic field definitions).
- `CHANGELOG.md` for known limitations and bug history.
