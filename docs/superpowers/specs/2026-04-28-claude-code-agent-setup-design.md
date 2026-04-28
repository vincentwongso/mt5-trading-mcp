# Claude Code agent setup — design

**Status:** Draft, awaiting Vincent's review.
**Date:** 2026-04-28.
**Goal:** Wire mt5-mcp into a Claude Code agent running in this repo, plus author project-scoped skills that teach the agent how and when to use the MCP's tools and resources. Lightweight smoke-test scope — first end-to-end agent exercise of the v1.0.1 server.

## Motivation

Phase 5 validated that mt5-mcp works against a live broker via direct test invocation. The next step is having an actual LLM agent drive the MCP. Claude Code is the simplest first agent: it discovers MCP servers via `.mcp.json` at the working directory, surfaces tools as `mcp__<server>__<tool>` calls, and applies `.claude/skills/` content as just-in-time guidance. Setting this up inside the repo means anyone who clones it can replicate the agent setup, and Vincent can iterate on the skills as the smoke test surfaces gaps.

## Scope

### In scope

1. **Project-scoped MCP client config** — `.mcp.json` at the repo root, stdio transport, no auth.
2. **Two project-scoped skills** under `.claude/skills/`:
   - `mt5-market-data/SKILL.md` — read-only tools and resources.
   - `mt5-trading/SKILL.md` — mutating tools and the consent-and-approval flow.
3. **Permissions** — `.claude/settings.json` allowlists read tools; mutating tools intentionally remain un-allowlisted to force a permission prompt on every trade.
4. **Documentation** — a "Using with Claude Code" section in `README.md`; one-line status update in `CLAUDE.md`.

### Out of scope

- HTTP-transport Claude Code config (the existing `examples/clients/claude-desktop-http.json` covers that shape).
- Slash commands, custom hooks, or sub-agents.
- A scripted end-to-end test harness — the verification is "open Claude Code in this repo and ask it questions."
- Architecture-doc changes; this is purely client-side wiring.
- Cross-machine agent setup (agent on a separate VPS talking to a remote MCP) — addressed by HTTP-transport when needed, not now.

## Architecture

### Component layout

```
mt5-trading-mcp/
├── .mcp.json                          # NEW — Claude Code MCP discovery
├── .claude/
│   ├── settings.json                  # MODIFIED — allowlist read tools
│   └── skills/                        # NEW
│       ├── mt5-market-data/
│       │   └── SKILL.md
│       └── mt5-trading/
│           └── SKILL.md
├── README.md                          # MODIFIED — Claude Code usage section
└── CLAUDE.md                          # MODIFIED — one-line status update
```

### `.mcp.json`

```json
{
  "mcpServers": {
    "mt5-mcp": {
      "command": "python",
      "args": ["-m", "mt5_mcp", "serve"]
    }
  }
}
```

stdio transport. The MT5 terminal must already be running and authenticated by the operator before Claude Code is launched in this directory; that's the production contract documented in CLAUDE.md (#23).

### Permissions posture

`.claude/settings.json` adds these MCP tool allow-rules to the existing `allow` array:

```
"mcp__mt5-mcp__ping",
"mcp__mt5-mcp__get_terminal_info",
"mcp__mt5-mcp__get_account_info",
"mcp__mt5-mcp__get_quote",
"mcp__mt5-mcp__get_symbols",
"mcp__mt5-mcp__get_market_hours",
"mcp__mt5-mcp__get_positions",
"mcp__mt5-mcp__get_orders",
"mcp__mt5-mcp__get_history"
```

Resource reads (`account://current`, `positions://current`, `quotes://*`) use Claude Code's resource-permission rule format, which is verified at implementation time against the current Claude Code docs (the rule shape has differed across versions). If resource reads still hit a prompt after the tool allowlist is in place, the implementation step adds the matching resource rule.

The four mutating tools (`place_order`, `modify_order`, `cancel_order`, `close_position`) deliberately stay outside the allowlist. Every mutating call fires an interactive permission prompt to Vincent — this is the human checkpoint **above** the policy engine's own consent flow. Defence in depth: the harness asks for permission, the engine asks for approval on large trades, and the broker enforces hard limits.

### Skill design

Each skill is a single `SKILL.md` with YAML frontmatter (`name`, `description`) and a body authored to teach the agent the minimal set of facts needed to use the MCP correctly. Both skills are flexible (informational), not rigid (procedural).

**`mt5-market-data/SKILL.md`** covers:

- Tool catalogue with one-line "use when" for each: `ping`, `get_terminal_info`, `get_account_info`, `get_quote`, `get_symbols`, `get_market_hours`, `get_positions`, `get_orders`, `get_history`.
- Resources: `account://current`, `positions://current`, `quotes://{symbol}` — when to read once vs subscribe.
- Output conventions: timestamps are aware-UTC; decimals are stringified; error envelopes carry `code` / `message` / `details` / `retryable`.
- Troubleshooting: always run `ping` first if anything looks wrong; `TERMINAL_NOT_CONNECTED` means the operator's MT5 client isn't connected to the broker.

**`mt5-trading/SKILL.md`** covers:

- The four mutating tools with brief signatures and "when to choose" guidance.
- The two-call consent flow: first call returns `approval_required` envelope with a `request_id` and a preview; the agent presents the preview to the human, then retries with `approval_confirmed=true`, `approval_request_id=<id>`, and **identical** other fields.
- Idempotency: always send `idempotency_key` on retries; the engine de-dupes by request hash excluding the approval fields.
- Pre-flight limit framing: `EXCEEDS_LOCAL_LIMIT` is a UX guardrail, not a security control; broker enforces real limits.
- Error taxonomy reference: `INVALID_APPROVAL`, `AUTO_TRADING_DISABLED`, `MARKET_CLOSED`, `TERMINAL_NOT_CONNECTED`, `INTERNAL_ERROR`.
- Demo-account framing: every order is a real order to the broker's MT5 server; demo means fake money, not fake execution.
- One worked `place_order` example showing the full preview → approval → execute round-trip.

Both skills end with a "see also" pointer to the architecture doc and the CHANGELOG for users who want depth.

### Triggering

Frontmatter `description` strings drive Claude Code's just-in-time skill loading.

- `mt5-market-data` description triggers on: querying account / balance / equity, getting a quote / price, listing symbols, checking positions / orders / trade history, asking about market hours, anything informational about the MT5 terminal.
- `mt5-trading` description triggers on: placing / opening a buy or sell order, closing a position, modifying SL / TP, cancelling a pending order, anything that mutates broker state.

Risk-boundary split is real: the agent only loads trading guardrails (consent flow, idempotency, demo framing) when it's actually about to trade, keeping the read path uncluttered.

## Data flow

```
User → Claude Code (in this repo) → reads .mcp.json
                                  → spawns `python -m mt5_mcp serve` (stdio child)
                                  → reads .claude/settings.json (permissions)
                                  → reads .claude/skills/ frontmatter for triggers
User asks question
  → Claude Code matches description, loads SKILL.md body
  → SKILL.md tells Claude which tools to call and how to interpret results
  → MCP tool calls go over stdio to the mt5_mcp child process
  → Child process talks to local MetaTrader5 terminal
  → Results flow back through stdio → Claude → User
```

For mutating tools, the harness inserts a permission prompt before the call leaves Claude Code, and the policy engine inserts an approval prompt at the response boundary if `notional ≥ auto_approve_notional`. Either gate can stop a trade.

## Error handling and edge cases

1. **Terminal not running** — first `ping` returns `TERMINAL_NOT_CONNECTED`. Skill instructs the agent to surface a clear "launch and log into MT5" message rather than retrying.
2. **Permission prompt denied** — Claude Code returns a tool-use error to the model; skill instructs the agent to acknowledge to the user and stop, not retry.
3. **Approval flow abandoned** — if the human declines after a preview, the agent drops the operation; no automatic retry. ApprovalStore expires the entry after `approval_ttl_seconds` regardless.
4. **Process restart mid-approval** — pending approvals live in-memory (CLAUDE.md #11). Skill notes this: if the MCP restarts between preview and confirmation, the human must re-issue the trade.
5. **Allowlist drift** — if a future MCP tool is added (`mcp__mt5-mcp__<new>`) it won't be allowlisted automatically; the agent will hit a permission prompt the first time. Acceptable.

## Testing

No automated tests. Verification is interactive:

1. Open Claude Code in this repo (`cd mt5-trading-mcp && claude`).
2. Confirm `mt5-mcp` shows in the MCP server list (`/mcp`).
3. Run a prompt that should trigger `mt5-market-data` ("what's my account balance?"). Verify the agent calls `get_account_info` without a permission prompt.
4. Run a prompt that should trigger `mt5-trading` ("buy 0.01 lots of BTCUSD"). Verify the agent: (a) hits a permission prompt for `place_order`, (b) once approved, surfaces a preview if notional triggers consent, (c) on retry uses the right idempotency key.
5. Confirm `audit.jsonl` has one entry per trade and the entries match what the agent did.

If any step fails, iterate on the SKILL.md content, not the production code.

## Trade-offs and rejected alternatives

- **One umbrella skill** — simpler, but loads trading guardrails for "what's my balance" queries. Rejected; risk-boundary split is a clean fit and free.
- **HTTP transport for the smoke test** — works, but stdio is one-step setup with no port or token to manage. HTTP shape is already exercised by the existing client examples.
- **Allowlisting mutating tools too** — would smooth the demo, but removes the human checkpoint on real-broker actions. Rejected on principle.
- **User-scoped skills (`~/.claude/skills/`)** — keeps the skills private, but means future cloners don't get the same agent setup, and the demo isn't reproducible. Rejected since broker-agnostic, demo-safe content is fine to ship.

## Open questions

None — all decisions made above. The spec is implementation-ready.

## Implementation note

Skills will be authored using the `skill-creator` skill so frontmatter and structure conform to the canonical format. The trading-domain content is hand-authored against the architecture doc and CHANGELOG.
