# Changelog

All notable changes to `mt5-mcp` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting at `1.0.0`.

## [1.0.11] - 2026-05-11

Bugfix release. v1.0.10's layered ping fallback fixed the
`terminal_info()`-only false negative, but each layer still called
mt5lib directly (bypassing the reinit-aware `self.call()` wrapper) on
the assumption that "ping should report raw IPC state." In practice,
when the IPC was in a NOT_INITIALIZED state that other read tools
transparently recover from, all three ping layers raised/returned None
in lockstep — so `ping.ok=false` while `get_account_info`,
`get_terminal_info`, and quotes all worked. Confirmed on the Broker
demo / FXVPS deployment immediately after upgrading to 1.0.10.

### Fixed

- `MT5Client.ping()` now routes each layer through `self.call(...)`,
  picking up the same transparent NOT_INITIALIZED → reinit → retry
  behavior every other read tool has. The earlier "ping bypasses
  retry" rule is dropped — the layered `via` field already supplies
  the per-source diagnostic that probe-vs-recovered consumers would
  have wanted from a raw probe.
- New regression test
  `test_ping_recovers_from_not_initialized_via_call_wrapper` pins the
  recovery path: a terminal_info() call that returns None+NOT_INITIALIZED
  on the first attempt triggers an in-wrapper reinit and the retry
  succeeds, surfacing `ok=true`, `via="terminal_info"`.

### Changed (docs)

- `CLAUDE.md` items #1 (`error_envelope` is tools-only) and #2b
  (`ctx.client.call()` as canonical access pattern) updated to remove
  the obsolete "ping bypasses retry" carve-out and reference the
  v1.0.11 routing change.

## [1.0.10] - 2026-05-11

Bugfix release. Surfaced when an MM cron monitor treated
`mt5-mcp__ping` `{"ok": false}` as terminal-down even though
`get_account_info`, quotes, and mutating tools all worked. Root cause:
the `ping` tool's only signal was `mt5.terminal_info()`, which some MT5
builds (notably v5.0.3815+ on the Broker demo / FXVPS deployment)
return as `None` despite a healthy session. The connect-time
broker-offset derivation already has a layered fallback for the same
quirk; `ping` was the lone single-source health check.

### Fixed

- `MT5Client.ping()` now uses a layered fallback mirroring
  `_derive_broker_offset`: (1) `terminal_info()` non-None, (2)
  `account_info()` with populated `login`, (3) a fresh tick
  (`<_FRESH_TICK_SECONDS`) on any `_BROKER_TIME_PROBE_SYMBOLS` symbol.
  Only when every layer is unavailable does `ping` report `ok=false`.
- Return shape extended from `(ok, latency_ms)` to `(ok, latency_ms,
  via)` where `via` names the layer that answered (`terminal_info`,
  `account_info`, `tick_probe`) or is `None` on failure. The MCP tool
  surfaces `via` in its response when present so monitors can
  distinguish "happy on the primary signal" from "primary flaked,
  recovered via fallback".
- Four new unit tests cover each layer plus the stale-tick rejection
  case; the existing "false when disconnected" test was reworded as
  "false when all layers fail" to match the new contract.

## [1.0.9] - 2026-05-11

Bugfix release. Surfaced when a downstream Stage 2 agent (`trader_cli`
placing a USOIL long on a live demo, ticket 88406038) called
`modify_order` with a malformed SL string. The bare `Decimal(sl)` inside
the tool body raised `decimal.InvalidOperation: ConversionSyntax`, which
`@error_envelope` swallowed as a generic `INTERNAL_ERROR` with no
field-or-value detail. The caller, unable to distinguish a caller-side
parse bug from an actual broker fault, treated it as a broker fault and
ran its "SL-modify failed → close position" branch, unwinding the
position for ~$94 of slippage. Same class of trap exists in `place_order`
for any of `volume`, `price`, `stop_limit_price`, `sl`, `tp`.

### Fixed

- `place_order` and `modify_order` now route every string-shaped Decimal
  argument through a new `_to_decimal(value, field=...)` helper that
  catches `InvalidOperation` / `ValueError` / `TypeError` and re-raises
  as `MT5Error(invalid_request_error(field=..., value=..., reason=...))`.
  Callers see a typed `INVALID_REQUEST` envelope with `details.field` and
  `details.value` instead of `INTERNAL_ERROR`. The order is never sent
  to the broker on a parse failure, so no naked-position window exists.
- New `invalid_request_error` factory in `errors.py` (mirrors the shape
  of the other `*_error` factories) for any future caller-side
  validation failure that needs the same envelope.
- New regression tests pin both surfaces:
  `test_modify_unparseable_sl_returns_invalid_request` and
  `test_unparseable_sl_returns_invalid_request` /
  `test_unparseable_volume_returns_invalid_request` (covers required vs
  optional Decimal fields).

## [1.0.8] - 2026-05-08

Bugfix release. Surfaced when a downstream agent (`trader_cli` driving Stage 3
position management against a live MT5 demo) attempted to trail an XAGUSD.z
stop-loss to breakeven and the mutating tool returned `INTERNAL_ERROR:
NoneType object has no attribute retcode` instead of a typed broker envelope.
Same trap fires for any caller of `place_order`, `modify_order`,
`cancel_order`, or `close_position` whenever `mt5lib`'s `order_send` rejects
the request locally (invalid stops, terminal disconnected, AutoTrading
toggled off mid-session, symbol freeze-level breach, etc.) — `mt5lib` returns
`None` rather than a result struct, and the conversion layer's
`int(raw.retcode)` raised `AttributeError` before the `@error_envelope`
decorator could map a retcode.

### Fixed

- `order_result_from_mt5_response` now detects `raw is None` and returns a
  typed `OrderResult{success=False, error.code="MT5_NULL_RESPONSE", ...}`.
  All four mutating tools benefit; agents see a deterministic envelope instead
  of an opaque `INTERNAL_ERROR`. The sentinel `server_response_code=0` is
  used (not a real `mt5lib` retcode) since the field is required `int` and
  there is no broker response to forward.
- New unit test `test_order_result_from_mt5_response_none_raw` pins the
  envelope shape so regressions surface immediately.

## [1.0.7] - 2026-05-02

Bugfix release. `load_config` now tolerates a UTF-8 BOM at the start of
`config.toml`. Surfaced when a Windows VPS user edited the file in Notepad
and got `tomllib.TOMLDecodeError: Invalid statement (at line 1, column 1)`
on next start — the BOM bytes (`EF BB BF`) parse as garbage before the first
`[`. Same trap fires for anyone using PS 5.1's `Set-Content -Encoding UTF8`,
which also writes a BOM by default.

### Fixed

- `load_config` reads `config.toml` with the `utf-8-sig` codec instead of
  bare `utf-8`. `utf-8-sig` strips the BOM if present and behaves
  identically to `utf-8` otherwise — no behavior change for files written
  without a BOM.

## [1.0.6] - 2026-05-02

Docs-only cleanup release. No functional changes versus `1.0.5`; the bundled
`CHANGELOG.md` and `tests/test_transport.py` no longer reference a specific
deployment hostname (replaced with `example.host.com`).

## [1.0.5] - 2026-05-02

Bugfix release. Surfaced when the HTTP transport sat behind a Tailscale serve
reverse proxy on a Windows VPS — the proxy forwarded the original
`Host: <machine>.<tailnet>.ts.net` header, which FastMCP's DNS-rebinding-
protection middleware rejected with `421 Misdirected Request` and an
`Invalid Host header` warning. Same shape would hit anyone fronting the MCP
with Cloudflare Tunnel, ngrok, nginx with `proxy_set_header Host $host`,
etc.

### Added

- `[transport.http] trusted_hosts` and `[transport.http] trusted_origins`
  config keys (both `list[str]`, default `[]`). Values are *appended* to
  FastMCP's existing localhost defaults (`127.0.0.1:*`, `localhost:*`,
  `[::1]:*`) — local-only setups need no config change. Operators behind a
  reverse proxy add their public-facing hostname:

  ```toml
  [transport.http]
  trusted_hosts = ["example.host.com"]
  trusted_origins = ["https://example.host.com"]
  ```

  DNS-rebinding protection itself stays on (FastMCP default); only the
  allow list is extended.

## [1.0.4] - 2026-05-01

Bugfix release. `mt5-mcp doctor` against a broker that doesn't expose a
literal `EURUSD` symbol (suffixed names like `EURUSD.r`, crypto-only brokers,
broker-specific naming) failed three checks (`get_quote`, `get_market_hours`,
`streaming`) instead of finding a workable symbol on its own.

### Fixed

- `--probe-symbol` now defaults to `auto`. The picker walks `BTCUSD, ETHUSD,
  EURUSD, XAUUSD, USDJPY, GBPUSD` in order, returns the first one the broker
  actually exposes, and falls back to the broker's first listed symbol if
  none of the candidates match. Brokers that expose no symbols at all get a
  `[SKIP]` message rather than three FAILs. Explicit `--probe-symbol <X>`
  still passes the symbol through unchanged (the user may want to see the
  SYMBOL_NOT_FOUND error). The selected symbol is logged on a `[INFO]` line
  so users can tell what was probed.

## [1.0.3] - 2026-05-01

Surface enrichment to support downstream reasoning skills (CFD trading skills consumer) plus a PyPI distribution rename. Pure adapter additions — no new mt5lib calls beyond `copy_rates_from_pos` and `order_calc_margin`. Backwards-compatible: existing tools and resources unchanged; `SymbolInfo` gains 13 new fields (additive, no renames).

### Added

- `SymbolInfo` enriched with broker-side fields the adapter previously dropped:
  - **Pricing & cash math:** `tick_value`, `tick_value_profit`, `tick_value_loss` — cash value of one tick in deposit currency, removing the need for downstream consumers to do their own currency conversion.
  - **Calc-mode dispatch:** `calc_mode` (string enum: `forex`, `cfd`, `cfd_index`, `cfd_leverage`, `forex_no_leverage`, `futures`, `exch_stocks`, `exch_futures`, `exch_futures_forts`, `exch_options`, `exch_options_margin`, `exch_bonds`, `exch_stocks_moex`, `exch_bonds_moex`, `serv_collateral`, `unknown`) — drives which margin formula applies per `EnCalcMode`.
  - **Margin parameters:** `margin_initial`, `margin_maintenance`, `margin_hedged` — per-symbol broker-set values used by futures/exchange calc modes.
  - **Swaps:** `swap_long`, `swap_short`, `swap_mode` (string enum: `disabled`, `by_points`, `by_base_currency`, `by_margin_currency`, `by_deposit_currency`, `by_interest_current`, `by_interest_open`, `by_reopen_current`, `by_reopen_bid`, `unknown`), `triple_swap_weekday` (string enum, `sunday`..`saturday`).
  - **Order-distance constraints:** `stops_level`, `freeze_level` (in points; multiply by `tick_size` for price).
- New tool `get_rates(symbol, timeframe, count)` returning OHLC bars. Timeframes: `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1`, `W1`, `MN1`. `count` clamped to `[1, 5000]`. Backed by `mt5.copy_rates_from_pos(...)`. Errors: `INVALID_TIMEFRAME`, `INVALID_COUNT`, `NO_RATES_AVAILABLE`, plus the usual `SYMBOL_NOT_FOUND` / `SYMBOL_NOT_ENABLED` from `SymbolPrep`.
- New tool `calc_margin(symbol, side, volume, price=None)` returning broker-authoritative margin in deposit currency. Wraps `mt5.order_calc_margin(...)`. When `price` is omitted, uses current ask (buy) / bid (sell) via `symbol_info_tick`. Errors: `MARGIN_CALC_FAILED` if the broker refuses (e.g. invalid volume step, market closed).
- `Bar` and `CalcMarginResult` Pydantic types in `mt5_mcp.types`.
- `rate_from_raw` and `calc_margin_result_from_raw` converters in `adapter/conversions.py`.

### Changed

- **PyPI distribution renamed `mt5-mcp` → `mt5-trading-mcp`.** The short name `mt5-mcp` was already taken on PyPI by an unrelated project (versions 0.4.0–0.5.2), which had quietly blocked every prior publish attempt. `1.0.3` is the first version actually published to PyPI; the `1.0.0`–`1.0.2` tags exist only as Git tags. Install command is now `pip install mt5-trading-mcp`. The CLI command (`mt5-mcp`), Python module (`mt5_mcp`), brand, repo URL, and storage paths are all unchanged — only the name on PyPI moves.
- `FakeSymbolInfo` extended with the broker-side fields above (sane defaults so existing tests are unaffected). `FakeMT5` gains `_copy_rates_from_pos`, `_order_calc_margin` slots and `TIMEFRAME_*` constants. New `FakeRate` dataclass.
- `mt5-market-data` skill SKILL.md updated to document the two new tools and the enriched `SymbolInfo`.

## [1.0.2] - 2026-04-28

Quality-of-life fix surfaced by the first Claude Code agent smoke test against Vincent's Broker demo terminal (UTC+3).

### Fixed

- Broker TZ offset is now derived from a probe-symbol tick when `terminal_info().time` is absent (the field isn't part of the documented stable Python API and several real MT5 builds omit it). `MT5Client.connect()` tries `terminal_info().time` first, then iterates `BTCUSD`, `ETHUSD`, `EURUSD`, `XAUUSD`, `USDJPY`, `GBPUSD` via `symbol_info_tick()`, validates the candidate offset against tick freshness (5-min residual) and a ±14h plausibility bound, and only falls back to `0` when no source can be sampled. Previously, every connect on builds missing `.time` silently used offset = 0, so all `time` fields in tool outputs were skewed by the broker's actual offset (typically +180 min for EET brokers).

## [1.0.1] - 2026-04-28

Production fixes surfaced by Phase 5 integration testing against a real MT5 demo terminal. `1.0.0` was tagged but never reached PyPI; `1.0.1` is the first build actually published.

### Fixed

- `place_order` (and any tool that goes through `pick_filling_mode`) crashed with `AttributeError: module 'MetaTrader5' has no attribute 'SYMBOL_FILLING_IOC'` against any live broker. The Python `MetaTrader5` module exports only `ORDER_FILLING_*` constants — the `SYMBOL_FILLING_*` symbol-side bitmask values must be inlined. Fixed in `src/mt5_mcp/adapter/symbols.py`. The `FakeMT5` test helper used to expose those attributes, masking the bug; it no longer does, so any future regression of this shape fails immediately in the unit suite.
- MT5 retcode `10027` ("AutoTrading disabled by client") was mapped to the generic `MT5_UNKNOWN_RETCODE` envelope. Now mapped to a dedicated `AUTO_TRADING_DISABLED` code with an actionable message ("Click the 'AlgoTrading' button in the MT5 toolbar so it turns green, then retry.").
- `get_positions` crashed with `AttributeError: 'TradePosition' object has no attribute 'commission'` against any live broker. The real MT5 `TradePosition` does not expose commission for open positions — commission is recorded per-deal at close time. Removed the `commission` field from the `Position` Pydantic model and from `position_from_raw` in `adapter/conversions.py`. Agents that need commission data should query `get_history`, where `Deal.commission` lives. `FakePosition` no longer exposes the field either.

## [1.0.0] - 2026-04-28

First public release on PyPI. The underlying feature set is the cumulative output of phases 1–3; this release adds packaging, public-facing documentation, and CI.

### Added

- Public PyPI distribution: `pip install mt5-mcp`.
- `SECURITY.md` with vulnerability disclosure policy and explicit scope statement (`mt5-mcp` is not the security boundary; the broker is).
- `CHANGELOG.md` (this file), retroactively documenting phases 1–3.
- `examples/clients/` directory with drop-in MCP-client configs:
  - `claude-desktop-stdio.json` — Claude Desktop stdio transport.
  - `claude-desktop-http.json` — Claude Desktop HTTP transport (for VPS / SSH-tunnel deployments).
  - `cursor.json` — Cursor stdio transport.
- README section on deploying `mt5-mcp` to a Windows VPS (Pattern A: agent on VPS; Pattern B: agent local with SSH tunnel to loopback HTTP).
- GitHub Actions test CI workflow (`pytest -m "not integration"` on Windows runners across Python 3.10 / 3.11 / 3.12, on push to `main` and on PRs).
- `[project.urls]` block in `pyproject.toml` (Repository, Issues, Changelog).

### Changed

- Bumped version `0.1.0` → `1.0.0`.
- README rewritten for first-time PyPI users; install instructions now lead with `pip install mt5-mcp`. Repo URL updated from `Broker/mt5-trading-mcp` to `vincentwongso/mt5-mcp`.
- `pyproject.toml` author updated from "Broker" to "Vincent". Security contact moved to a personal email.

### Removed

- Internal phase-tracking references (`phase-2-complete`, "243 passing unit tests" status lines, etc.) removed from public-facing docs. They remain in `CLAUDE.md` for contributors.

## [0.3.0] - 2026-04-27

Resources, HTTP transport, and streaming subsystem (Phase 3, internal release).

### Added

- Three subscribable MCP resources: `account://current`, `positions://current`, `quotes://{symbol}`.
- Streaming subsystem (`src/mt5_mcp/streaming/`): a single shared `Poller` daemon thread + `Dispatcher` for per-URI change-fanout.
- HTTP transport (`serve --transport http`), loopback-only, with optional bearer-token auth (`transport.http.auth_token`).
- `[streaming]` config section with configurable poll cadences (`quote_poll_ms`, `account_poll_ms`).
- `doctor` gained a `[streaming]` check.
- `FastMCPSubscriber` adapter bridging the Poller's daemon thread to the FastMCP asyncio event loop.

### Changed

- Change-detection for `account://current` and `positions://current` excludes floating P&L by design — only identity/structural changes wake subscribers.

## [0.2.0] - 2026-04-26

Mutating tools and policy engine (Phase 2, internal release).

### Added

- Four mutating MCP tools: `place_order`, `modify_order`, `cancel_order`, `close_position`.
- Policy engine (`src/mt5_mcp/policy/`) composing four submodules: `preflight`, `consent`, `idempotency`, `audit`.
- SQLite-backed idempotency replay (per-OS path via `platformdirs`).
- Append-only JSONL audit log with size-based rotation.
- `doctor --smoke-trade` flag for live-terminal verification of the place-then-close round-trip.

### Changed

- Approval flow simplified to a single `approval_confirmed` boolean + `approval_request_id`; the earlier HMAC-signed token design was dropped.
- "Soft limits" renamed "Pre-flight limits" with explicit non-security framing (architecture §8).

## [0.1.0] - 2026-04-24

Skeleton and read tools (Phase 1, internal release).

### Added

- Nine read MCP tools: `ping`, `get_terminal_info`, `get_account_info`, `get_quote`, `get_symbols`, `get_market_hours`, `get_positions`, `get_orders`, `get_history`.
- Two CLI commands: `doctor`, `export-symbols`.
- `MetaTrader5`-wrapping adapter with a singleton client, symbol prep, and type conversions.
- Config loader with `watchdog`-based hot-reload.
- FastMCP server bootstrap.
- 89 unit tests against a hand-rolled `FakeMT5` (no live terminal needed).
