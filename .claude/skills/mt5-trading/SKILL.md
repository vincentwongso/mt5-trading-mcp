---
name: mt5-trading
description: Use when the user wants to place, modify, cancel, or close a real trade on their MetaTrader 5 broker — including market orders, limit / stop / stop-limit orders, adjusting stop-loss or take-profit, cancelling pending orders, or closing a position in full or part. Triggers on phrases like "buy 0.1 lots of EURUSD", "go short BTCUSD", "close my XAUUSD position", "move my stop to break-even", "cancel that pending order", "open a long". Always use this skill before any tool call that mutates broker state — it carries the consent flow, idempotency rules, and broker-specific failure modes that you must follow to avoid losing the user money.
---

# Trading on MetaTrader 5 — mutating tools

This skill covers the four mutating tools the `mt5-mcp` server exposes. **Every successful call here is a real broker action.** Even on a demo account, the trade reaches the broker's MT5 server and is irreversible from the agent's side — the only way to undo a wrong order is another order. Treat the consent flow described below as the line that separates "I told the user what I'm about to do" from "I just did something the user didn't sign off on".

## Tool catalogue

**`place_order(symbol, side, type, volume, price?, stop_limit_price?, sl?, tp?, deviation=10, comment?, idempotency_key?, approval_confirmed=false, approval_request_id?)`** — open a new market or pending order. `side` is `"buy"` or `"sell"`. `type` is `"market"`, `"limit"`, `"stop"`, or `"stop_limit"`. `volume` is in lots, as a string (e.g. `"0.10"`).

**`modify_order(ticket, sl?, tp?, price?, expiration?, idempotency_key?, approval_confirmed=false, approval_request_id?)`** — adjust a position's SL/TP (positions only), or a pending order's price / expiration / SL / TP. **Widening or removing an existing SL/TP on a position requires approval; tightening auto-approves.** Pass `expiration` only for pending orders, as ISO 8601 UTC.

**`cancel_order(ticket, idempotency_key?)`** — remove a pending order. Never gates for approval (cancelling reduces exposure).

**`close_position(ticket, volume?, idempotency_key?, approval_confirmed=false, approval_request_id?)`** — close a position in full (omit `volume`) or part (pass a smaller string volume).

All mutating tools return a result envelope on success: `{retcode, deal, order, volume, price, comment, request_id?, request_echo}`. Surface `deal` and `price` to the user — that's the executed fill.

## The two-call approval flow

For `place_order`, `modify_order` (when widening), and `close_position`, the policy engine compares the trade's notional value against `policy.auto_approve_notional` (default 1,000 in account currency). Above that threshold the **first** call returns an `ApprovalPreview` envelope instead of executing:

```
{
  "approval_required": true,
  "preview": {
    "request_id": "01HQX...",
    "expires_at": "2026-04-28T19:55:00+00:00",
    "summary": "BUY 0.10 EURUSD @ market (~1085 USD)",
    "action": "place_order", "symbol": "EURUSD",
    "notional": "1085.12", "estimated_margin": "10.85",
    "reference_quote": {"symbol": "EURUSD", "bid": "1.08510", "ask": "1.08515", "time": "..."},
    "request_echo": { ...all the fields the agent originally sent... }
  }
}
```

When you receive this, **do not retry automatically**. Show the user a short, plain-English version of the preview — direction, size, symbol, approximate notional, estimated margin — and ask them to confirm. Only after they say yes do you make the second call:

- Same tool, same `symbol` / `side` / `type` / `volume` / `ticket` / `price` (everything that was in `request_echo`).
- Add `approval_confirmed=true`.
- Add `approval_request_id=<the request_id from the preview>`.

If you change any of those fields between preview and confirm, the engine returns `INVALID_APPROVAL` ("request body changed since preview"). That's by design — it stops a bait-and-switch where the agent shows the user one trade and submits another.

If `approval_confirmed=true` but no preview was ever issued, or the `request_id` doesn't exist (e.g., the server restarted, or it expired after `approval_ttl_seconds` — default 300s), you also get `INVALID_APPROVAL`. The right response is to drop the confirmation flag and start the flow over: present a fresh preview to the user and ask again.

## Idempotency

Always send an `idempotency_key` on **retries**, and always make it a UUIDv4 (or any unique string the user gives you). The engine remembers the result of the first call keyed by request hash; any subsequent call with the same key and the same request body returns the cached result instead of placing a duplicate trade. Two important rules:

- **The hash excludes `approval_confirmed` and `approval_request_id`.** A preview-then-confirm pair counts as one logical request — the second call returns the cached approval-required envelope unless the user has confirmed.
- **Same key, different body → `IDEMPOTENCY_DIVERGED`.** That's an agent bug. Use a fresh key for distinct requests; reuse a key only when retrying *the same* trade.

For a fresh trade, omitting `idempotency_key` is fine — the engine generates one. Only set it explicitly when you're retrying after a network blip, ambiguous error, or a deliberate "make sure this is the same trade" flow.

## Pre-flight limits

The server enforces a few configurable local limits before a trade reaches the broker (`policy.preflight.*`). These are UX guardrails — they protect the user from agent slip-ups, not from the broker. The broker enforces real margin and leverage; these checks just refuse obviously too-large requests early. The most common refusal:

- `EXCEEDS_LOCAL_LIMIT` with `details.limit_name="notional_per_request"` — the trade's notional is above the configured per-request cap. Tell the user the cap; let them decide whether to split the trade or raise the cap (config edit, server reload).

## Error taxonomy

You'll see most of these from mutating tools. Treat the `requires_human` flag as authoritative — when it's true, stop and surface the issue to the user; don't retry without their input.

- `AUTO_TRADING_DISABLED` (mt5 retcode 10027) — the MT5 toolbar's "AlgoTrading" button is red. **Only the human can fix this**: tell them to click that button so it turns green, then ask if they want to retry.
- `MARKET_CLOSED` (10018) — the symbol's session is closed. Either wait, or pick another symbol.
- `REQUOTE` (10004) — price moved between submission and execution. Retryable; same idempotency key, same body, the engine will resubmit.
- `INVALID_PRICE` (10015) — the price you sent is invalid for the order type (e.g., a stop above market for a buy stop). Recheck and resubmit with a fresh price.
- `INVALID_VOLUME` (10014) — volume doesn't match the symbol's lot step / min / max. Use `get_symbols` to look up the right step.
- `INSUFFICIENT_MARGIN` (10019) — not enough free margin. Surface the user's current margin from `get_account_info` so they can decide.
- `REJECTED_BY_SERVER` (10006) — the broker said no, often without specifics. Don't retry blindly; tell the user.
- `EXCEEDS_LOCAL_LIMIT` — see above.
- `INVALID_APPROVAL` — preview/confirm mismatch or expired preview. Re-do the consent flow.
- `INVALID_TICKET` — ticket doesn't exist (closed, cancelled, never existed). Use `get_positions` / `get_orders` to find the right ticket.
- `TERMINAL_NOT_CONNECTED` — the operator's MT5 client isn't connected. Tell them to log in, then retry.
- `INTERNAL_ERROR` — unexpected exception. Don't retry; surface to the user.

## Demo account framing

If the user's account is a demo, the money is fake but **the execution is real**. The order goes to a live broker server, fills against live or simulated liquidity, opens a real position object with a ticket, and gets reported in `audit.jsonl`. Do not treat demo as "tests don't matter" — the main reason the human is using a demo terminal is to verify your behaviour before they switch to live.

## Worked example: `place_order` round-trip

User: "Buy 0.10 lots of EURUSD at market."

1. **Quote first** so the user has context: `get_quote(symbol="EURUSD")` → bid 1.08510, ask 1.08515.
2. **First call**:
   ```
   place_order(symbol="EURUSD", side="buy", type="market", volume="0.10")
   ```
3. **If the server returns** `approval_required: true` (because the notional 1.0851 × 0.10 × 100,000 ≈ 10,851 USD is above the configured threshold), present this to the user verbatim:
   > "About to BUY 0.10 EURUSD at market — roughly 10,851 USD notional, ~10.85 USD margin at your leverage. Confirm?"
   Wait for an explicit yes. Don't infer consent from the user's earlier "buy 0.10 lots" — that's the original request, not a confirmation of the preview.
4. **Second call** (only after explicit yes):
   ```
   place_order(symbol="EURUSD", side="buy", type="market", volume="0.10",
               approval_confirmed=true, approval_request_id="<the request_id from preview>")
   ```
5. **On success**, the result envelope carries `deal`, `order`, `price`, `volume`. Tell the user: "Filled at 1.08516 — 0.10 lots EURUSD long. Position ticket 12345678."
6. **If `approval_required: false`** on the first call (small enough trade), the result is the fill directly — same final report.

## Workflow rules

1. **Always quote before opening.** A `get_quote` (or `get_market_hours`) before `place_order` catches stale-symbol and market-closed cases without a wasted approval round.
2. **Always read the position before modifying or closing.** A `get_positions(symbol=...)` confirms the ticket exists and surfaces its current SL/TP — useful context for the user before changes.
3. **Surface fills, not retcodes.** The user wants to know they're in at 1.08516, not that retcode 10009 (TRADE_DONE) came back. Translate.
4. **Don't loop on errors.** If a trade fails with anything that isn't explicitly `retryable=true`, stop and tell the user. Especially never retry an `INSUFFICIENT_MARGIN` or `INVALID_VOLUME` — those need human input.
5. **Cancel ≠ close.** `cancel_order` removes a pending order that hasn't filled; `close_position` closes a filled position. The user often blurs these — confirm which they mean if their phrasing is ambiguous.

## See also

- `mt5-market-data` skill — covers the read-only side. Use those tools to gather context (quotes, positions, account state) before mutating.
- `CLAUDE.md` (project root) sections on the policy engine and consent flow for the full architectural picture.
- `audit.jsonl` (operator-side, default `~/.local/share/mt5-mcp/audit.jsonl`) records every mutating call. Useful for the user to verify what was done.
