---
name: mt5-market-data
description: Use when the user asks about their MetaTrader 5 broker account, balance, equity, margin, open positions, pending orders, trade history, current quotes / prices / bid-ask, tradeable symbols, market hours, or whether a symbol is currently tradeable. Triggers on questions like "what's my P&L", "show me my positions", "what's the price of EURUSD", "is the gold market open", "any pending orders on BTCUSD", "what trades did I do last week". Always use this skill before reaching for shell tools or web searches when the question is about MT5 broker state — the MCP has direct access.
---

# Reading MetaTrader 5 broker state

The `mt5-mcp` MCP server exposes nine read-only tools and three resources that read live data from a running MetaTrader 5 terminal. Use them whenever the user wants to know the state of their account, market, or trading history. None of these tools mutate broker state — call them freely without confirmation.

## Tool catalogue

Each tool name below is the MCP tool name (Claude Code surfaces them as `mcp__mt5-mcp__<tool>`).

**`ping`** → `{ok: bool, latency_ms: int}` — health check. Cheap; call this first if anything looks wrong (especially if a previous call returned `TERMINAL_NOT_CONNECTED`).

**`get_terminal_info`** → broker server name, login, latency, broker timezone offset. Use when the user asks "what broker am I connected to" or you need to confirm the terminal is healthy before a sequence of reads.

**`get_account_info`** → balance, equity, margin, free margin, leverage, currency, margin mode. Use for any question about account state, P&L (equity − balance ≈ floating P&L), or buying power.

**`get_quote(symbol)`** → current `bid`, `ask`, `time` for one symbol. Use when the user asks about the current price, spread, or last tick. Symbols are auto-prepared in Market Watch on first use.

**`get_symbols(category=None)`** → list of tradeable instruments with metadata (point, digits, contract size, lot step, etc.). Optionally filter by category like `"Forex"` or `"Metals"`. Use when the user wants to discover what they can trade or needs symbol metadata before placing an order.

**`get_market_hours(symbol)`** → `{symbol, is_open, next_open, next_close}`. **v1 limitation: `next_open` and `next_close` are always `None`.** Only `is_open` (derived from broker `trade_mode`) is reliable. If the user wants precise session boundaries, point them at their broker's published schedule.

**`get_positions(symbol=None)`** → list of open positions. Each carries ticket, symbol, side, volume, open price, current price, SL, TP, swap, profit, and open time. Use for "show me my positions" / "what am I holding" / "P&L per trade".

**`get_orders(symbol=None)`** → list of pending orders (limit / stop / stop-limit). Distinct from positions — these haven't filled yet.

**`get_history(from_ts, to_ts, symbol=None)`** → closed deals in the given UTC ISO 8601 range. Both timestamps must include a timezone (`Z` or `+00:00`); naive timestamps are rejected with `INVALID_TIMESTAMP`. Use for "what trades did I do yesterday / last week / since X".

## Resources

The server also exposes three subscribable MCP resources. Read them when the user wants a snapshot framed as "the current state of X" rather than "give me X":

- `account://current` — same shape as `get_account_info`. Subscribe for live equity/margin updates.
- `positions://current` — list of open positions. Subscribe to see opens / closes / SL-TP changes as they happen. **Floating P&L is not a change-detection trigger** — the resource only re-pushes when something structural changes (open, close, ticket attribute change), not on every tick.
- `quotes://{symbol}` — replace `{symbol}` with e.g. `quotes://EURUSD`. Subscribe for streaming bid/ask updates on that symbol.

For one-shot reads, prefer the equivalent tool — it's more obvious in transcripts. Subscribe to a resource only when the user genuinely wants a stream (e.g., "watch this" / "let me know when X").

## Output conventions

- **Timestamps are aware UTC.** All `time`, `time_setup`, `expiration`, etc. come back as ISO 8601 strings ending in `+00:00`. Convert to the user's local timezone in the response if it helps readability.
- **Decimals are stringified.** Prices, volumes, P&L, and limits are JSON strings (`"1.08512"`, `"0.10"`) so you don't lose precision through floats. When doing arithmetic, convert via `Decimal(...)` mentally / explicitly; never mix string-money with float-money.
- **Empty results are `[]`, not an error.** No positions, no pending orders, and no history matches all return an empty list.

## Errors

Tool failures arrive as MCP errors carrying a structured envelope: `{code, message, retryable, requires_human, details, mt5_retcode?}`. Common codes you'll see from read tools:

- `TERMINAL_NOT_CONNECTED` — operator hasn't launched MT5 or hasn't logged into the broker. Tell the user to open MT5 and log in, then retry.
- `SYMBOL_NOT_FOUND` — typo in symbol name. Suggest `get_symbols` to discover the right name.
- `SYMBOL_NOT_ENABLED` — symbol exists but has no tick data right now (market closed, broker maintenance). Often retryable later.
- `INVALID_TIMESTAMP` — `get_history` was called with naive or malformed timestamps. Always use `+00:00` or `Z`.
- `INTERNAL_ERROR` — unexpected server-side exception. The full traceback is logged on the MCP server; the envelope only carries the exception type. Surface it cleanly to the user — don't retry blindly.

## Workflow tips

1. **Diagnostic posture.** When the user reports something off ("why is my equity wrong?"), start with `ping` → `get_terminal_info` → `get_account_info` to confirm the connection and account state before drilling into specific symbols.
2. **One symbol vs all.** `get_positions(symbol="EURUSD")` is much cheaper than fetching all and filtering client-side. Use the optional symbol filter when you have one in hand.
3. **Prefer tools over resources for one-shot questions.** Resources shine for "watch this" requests; for "what's the price right now", `get_quote` is the right call.
4. **Don't compose your own broker schedules.** If the user wants "when does FX open Sunday night", consult their broker's website — `get_market_hours` only tells you whether it's open *now*.

## See also

- `mt5-trading` skill — covers placing, modifying, cancelling, and closing orders. Loads automatically when the user wants to actually trade.
- Architecture spec at `mt5-mcp-architecture.md` for the full data model.
- `CHANGELOG.md` for known limitations and bug history.
