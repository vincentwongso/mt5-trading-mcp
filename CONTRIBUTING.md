# Contributing to mt5-mcp

Thanks for your interest in improving `mt5-mcp`. This is a high-level guide —
the deep architecture notes and invariants live in
[`CLAUDE.md`](CLAUDE.md).

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

## Code style & invariants

There's no enforced linter; match the style of the surrounding code. A few
invariants are easy to break and are documented in detail in
[`CLAUDE.md`](CLAUDE.md) — the most important:

- **Timestamps are aware-UTC only**, produced by the adapter's conversion layer.
  Never construct a naive `datetime`.
- **Route mt5lib data calls through `ctx.client.call(...)`** (the reinit-aware
  wrapper); only constants bypass it.
- **Tools use the `@error_envelope` pattern** and call `get_context()` as the
  first line — they don't take a `ctx` parameter.
- **Production code must never import from `tests.`** Extend the typed fakes in
  `tests/fakes.py` rather than reaching for `MagicMock`.

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
