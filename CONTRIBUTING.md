# Contributing to mt5-mcp

Thanks for your interest in improving `mt5-mcp`. This guide covers how to
contribute, the dev setup and test workflow, and the architecture invariants
that are easy to break.

## Ways to contribute

- **Report a bug** — open a GitHub issue with steps to reproduce, your OS, your
  Python version, and the relevant `python -m mt5_mcp doctor` output.
- **Request a feature** — open an issue describing the use case. Please check
  the [CHANGELOG.md](CHANGELOG.md) "known limitations" and the project
  principles below first; some things are deliberately out of scope for v1.
- **Send a pull request** — for anything non-trivial, open an issue first so we
  can agree on the approach before you invest time.
- **Improve the docs** — corrections and clarifications to the
  [`docs/`](docs/) pages are very welcome.

## Project principles

Keep these in mind — they shape what gets accepted:

- **Broker-agnostic.** No hardcoded broker URLs, server names, or symbol
  conventions. The reference broker is not an embedded constraint.
- **Local-first.** No cloud component, no telemetry by default, no auto-update.
  The MCP runs on the user's machine in the same process tree as their agent.
- **The MCP is not the security boundary.** The broker's MT5 server enforces the
  hard limits. The policy engine's pre-flight checks are UX guardrails to catch
  agent mistakes early — not security controls. Don't frame them as such.

## Development setup

```bash
git clone https://github.com/vincentwongso/mt5-trading-mcp.git
cd mt5-trading-mcp
uv sync --extra dev
```

(See [docs/installation.md](docs/installation.md) for the Linux/Docker bridge
setup if you need a live terminal.)

## Running tests

The unit suite uses a hand-rolled `FakeMT5` and needs **no live terminal**:

```bash
uv run pytest -v                    # full suite
uv run pytest -m "not integration"  # unit tests only
```

Always run the full suite before opening a PR — the autouse fixtures in
`tests/conftest.py` are load-bearing for test isolation.

Live-terminal smoke checks (require a running MT5 terminal logged into a broker;
the smoke-trade variant places a real micro-lot order — **use a demo account**):

```bash
python -m mt5_mcp doctor
python -m mt5_mcp doctor --smoke-trade
```

The end-to-end `tests/integration/` suite drives the server against a real MT5
demo terminal — see [docs/installation.md](docs/installation.md) and
`tests/integration/.env.example` for the requirements. Run it with
`pytest -m integration -v`.

CI runs the unit suite on Windows runners across Python 3.10 / 3.11 / 3.12 on
every push to `main` and every PR.

## Code style

There's no enforced linter; match the style of the surrounding code — its
comment density, naming, and idioms.

## Architecture invariants

The codebase has a handful of non-obvious invariants that are easy to break.
Please keep these in mind — PRs that violate them will be sent back.

### Tools & error handling

- **Tools take no `ctx` parameter.** FastMCP can't build a JSON schema for
  `AppContext`, so the planned `def tool(ctx, ...)` signature doesn't work. Wrap
  the tool with `@error_envelope` and call `get_context()` as the **first line**
  of the body. `ping` is the one deliberate exception — it returns its
  structured health dict directly so callers can read it even on failure.
- **Use the error factories** in `errors.py` (`terminal_not_connected_error()`,
  `internal_error(exc)`) rather than inlining `ErrorDetail(...)`. The envelope
  decorator catches everything and never lets a Python traceback reach the
  client.
- **Route mt5lib data calls through `ctx.client.call(...)`** — the reinit-aware
  wrapper that makes transparent reconnect real. Only MT5 *constants*
  (`m.ORDER_FILLING_IOC`, etc.) may be read directly off `ctx.client.mt5`.
- **Resources are different.** Resource handlers do **not** use
  `@error_envelope`; they raise `MT5Error(...)` and let FastMCP render the
  protocol error.

### Mutating tools & the policy engine

- Every mutating tool computes its own `requires_approval` and routes through
  `ctx.policy.guard(...)`; the engine owns idempotency, consent, and audit. The
  stage order is load-bearing — idempotency → confirmed-consent → pre-flight →
  first-pass-consent → execute — so a bait-and-switch on a confirmed approval
  surfaces as `INVALID_APPROVAL`, not `EXCEEDS_LOCAL_LIMIT`.
- `request_hash` **excludes** the `approval_*` fields, so a retry with the same
  idempotency key replays the cached result regardless of approval token.
- The `ApprovalStore` is in-memory and single-use; a process restart
  invalidates pending approvals by design (the human re-confirms against current
  state).

### Timestamps

- **Aware-UTC only**, enforced by the Pydantic `_Base` validator in `types.py`.
  Never construct a naive `datetime`. The adapter's
  `epoch_to_utc(epoch, broker_offset_minutes)` is the single producer — don't
  add another timestamp source.
- The broker-timezone offset is derived at connect time with a three-layer
  fallback (`terminal_info().time` → freshest probe-symbol tick → `0`). Preserve
  all three — brokers on EET (UTC+3) get every timestamp wrong if it silently
  degrades to `0`.

### Testing

- **Production code must never import from `tests.`** Extend the hand-rolled
  typed fakes in `tests/fakes.py` instead of reaching for `MagicMock` — the
  strong typing makes missing test data fail loudly.
- Use UTC-portable epochs:
  `int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())`. A naive
  `.timestamp()` is read as local time and breaks tests on non-UTC machines.
- **Sandbox storage under `tmp_path`.** Pass `config_path=tmp_path/"config.toml"`
  to `build_server(...)` so the idempotency DB and audit JSONL land in a
  sandbox. A test that writes to the real `~/.local/share/mt5-mcp/audit.jsonl`
  is a defect — that log is the operator's record of intentional trading.
- Integration tests keep the `assert_clean_account` guard (they refuse to run
  against an account with open positions/orders), use a **demo** account, and
  crank `auto_approve_notional` rather than exercising the consent gate live.

### Storage & config

- Storage paths come from config and default to
  `platformdirs.user_data_dir("mt5-mcp", appauthor=False)`. The
  `appauthor=False` matters — without it Windows produces a doubled
  `mt5-mcp\mt5-mcp\` path. Never hard-code these.

### FastMCP integration quirks

Only relevant if you touch the transport or streaming subsystems — these are
version-specific shims with no obvious alternative:

- The HTTP transport sets `mcp.settings.host` / `mcp.settings.port` **before**
  `mcp.run(...)`; `run()` does not accept them as kwargs. `transport.py` is the
  single place to update if a future FastMCP changes this.
- Resource subscribe/unsubscribe hooks go through the low-level
  `mcp._mcp_server.subscribe_resource(...)`. The Poller daemon thread bridges to
  the asyncio loop via `asyncio.run_coroutine_threadsafe` — never call the
  session methods directly from the Poller thread.

## Submitting a pull request

1. Branch off `main`.
2. Add or update tests for your change.
3. Make sure `uv run pytest -v` passes.
4. Update [CHANGELOG.md](CHANGELOG.md) under an "Unreleased" heading and the
   relevant [`docs/`](docs/) page if behaviour changed.
5. Open the PR with a clear description and link the issue it addresses.

## Security

Please **do not** open public issues for security vulnerabilities. Follow the
disclosure process in [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
