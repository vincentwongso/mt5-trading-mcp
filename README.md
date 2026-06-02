# mt5-mcp

[![PyPI version](https://img.shields.io/pypi/v/mt5-trading-mcp.svg)](https://pypi.org/project/mt5-trading-mcp/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/mt5-trading-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/vincentwongso/mt5-trading-mcp/test.yml?branch=main&label=tests)](https://github.com/vincentwongso/mt5-trading-mcp/actions/workflows/test.yml)

Model Context Protocol server wrapping the MetaTrader 5 Python library: exposes
a logged-in MT5 terminal as a set of MCP tools an AI agent can call.

<p align="center">
  <img src="demo/mt5-mcp-demo.gif" width="600" alt="mt5-mcp demo: an AI agent places and closes a live trade over MCP"><br>
  <sub>A <a href="https://github.com/NousResearch">Hermes</a> agent placing then closing a real 0.01-lot trade on a <b>demo</b> account, end-to-end over MCP on Linux.</sub>
</p>

<p align="center">
  <img src="demo/mt5-history.png" width="600" alt="The same round-trip in MetaTrader 5's History tab"><br>
  <sub>Not a mock-up — the same round-trip in MetaTrader 5's own History tab; the tickets and balance match the recording.</sub>
</p>

> ⚠️ **This software places _real_ trades through your MetaTrader 5 terminal with
> real orders and irreversible fills.** Read [DISCLAIMER.md](DISCLAIMER.md)
> and [SECURITY.md](SECURITY.md) before connecting it to a live account. Always test
> using your demo account first.

Windows (native) or Linux (via Docker); Python 3.10+.

## What it is

`mt5-mcp` lets an AI agent read your MetaTrader 5 account and place trades
through it, over the Model Context Protocol. It runs locally, in the same
process tree as your agent, no cloud, no telemetry.

- **11 read-only tools**: account, quotes, positions, orders, history, OHLC
  bars, and broker-authoritative margin estimates. No consent gate.
- **4 mutating tools**: `place_order`, `modify_order`, `cancel_order`,
  `close_position`, each behind a preflight + human-consent + idempotency +
  audit layer.
- **3 subscribable resources**: live `account://`, `positions://`, and
  `quotes://{symbol}` snapshots that push change notifications.

Full catalogue and the consent flow: **[docs/tools.md](docs/tools.md)**.

## Quickstart (Windows, native)

```bash
pip install mt5-trading-mcp
```

1. Launch MetaTrader 5 and log into your broker. Enable **AlgoTrading** (toolbar
   button green).
2. Verify the terminal is reachable: `python -m mt5_mcp doctor`: expect
   `[INFO] backend: native` and `[PASS]` lines.
3. Run it: `python -m mt5_mcp serve`.

**Linux** (the MT5 terminal runs in an all-in-one Docker image; the agent talks
MCP over HTTP) and **wiring to an agent** are in
**[docs/installation.md](docs/installation.md)**.

## For AI agents

**If you are an AI agent and have been handed this repository to install and
run, follow this procedure.**

1. **Detect the platform and pick a backend.** Windows runs the `MetaTrader5`
   library natively; Linux runs the terminal in an all-in-one Docker image (the
   agent talks MCP over HTTP). Full per-platform steps:
   **[docs/installation.md](docs/installation.md)**.
2. **Install from this checkout:**
   - **Windows:** `pip install .` (or `uv sync --extra dev`). Tell the human to
     launch MetaTrader 5, log into their broker, and enable **AlgoTrading**.
   - **Linux (recommended):** bring up the Docker image — creds in
     `deploy/.env`, then `docker compose -f deploy/docker-compose.yml up -d`
     (it uses the published image; add `--build` only for local `deploy/`
     changes). The server runs in the container and serves MCP over HTTP; the
     one-time VNC login + bridge alternative are in `docs/installation.md`.
3. **Verify before doing anything else:** Windows → `python -m mt5_mcp doctor`
   (expect the backend + `[PASS]` lines); Docker image → after the human's
   one-time VNC login, your first `ping` returns `ok: true`. Do **not** proceed
   if verification fails — report it to the human and stop.
4. **Register / run the server:** Docker image → it's already serving; register
   `http://127.0.0.1:8765/mcp`. Windows → `python -m mt5_mcp serve` (stdio) with
   a config under [`examples/clients/`](examples/clients/) (e.g.
   [`hermes.json`](examples/clients/hermes.json)) that scopes you to the
   read-only tools by default.
5. **Operate read-only unless explicitly asked to trade.** The read tools are
   safe to call freely.
6. **⚠️ Hard rule, if live account and using real money.** `place_order`, `modify_order`, and
   `close_position` execute **real, irreversible trades**. When one returns an
   `ApprovalPreview`, show it **verbatim** to the human and only retry with
   `approval_confirmed=true` after they explicitly approve **that specific
   order**. Never auto-confirm, never batch-approve, never trade on a demo
   assumption — confirm it's a demo account first.

Tool semantics and the full consent flow: **[docs/tools.md](docs/tools.md)**.
Under Claude Code, cloning this repo wires up the MCP server (`.mcp.json`) and
auto-loads the `.claude/skills/` (market-data + trading) — see
**[docs/clients.md](docs/clients.md)** for how that fits together.

## Documentation

| Guide | What's in it |
|---|---|
| [Installation & setup](docs/installation.md) | Requirements, Windows + Linux/Docker setup, wiring to an agent. |
| [Configuration](docs/configuration.md) | `config.toml` schema, storage paths, hot-reload. |
| [Tools & resources](docs/tools.md) | Read tools, mutating tools + consent flow, subscribable resources. |
| [MCP client setup](docs/clients.md) | Per-client config snippets and Claude Code usage. |
| [Transports & deployment](docs/deployment.md) | stdio/HTTP transports and Windows VPS patterns. |
| [Contributing](CONTRIBUTING.md) | How to contribute and run the tests. |
| [Changelog](CHANGELOG.md) | Release history and known limitations. |

## Safety

`mt5-mcp` is **not** the security boundary, the broker's MT5 server enforces
the hard limits (margin, max-lot, symbol permissions). Pre-flight checks in the
policy engine are UX guardrails to catch agent mistakes early, not security
controls.

Mutating actions above the configured `auto_approve_notional` (or that widen
stops) require explicit human approval via the `ApprovalPreview` flow. Every
mutating call is recorded in an append-only audit JSONL log. For vulnerability
disclosure, see [SECURITY.md](SECURITY.md).

## Architecture

`mt5-mcp` wraps the MetaTrader 5 Python library behind a FastMCP server. A single `MT5Client` owns the terminal connection, broker-timezone inference, and type conversions; everything else sits on top of it. The Pydantic models in `types.py` / `config.py` are the source of truth for the data and config schemas.

```
     Agent / MCP client  (Claude Code, Claude Desktop, …)
                               │
                               │   stdio  ·  loopback HTTP
                               ▼
 ┌──────────────────────────────────────────────────────────┐
 │                      FastMCP server                      │
 │                                                          │
 │   tools/        resources/        policy/                │
 │   read +        subscribable      consent · idempotency  │
 │   mutating      account/quotes    · audit (JSONL)        │
 │                                                          │
 │   streaming/  — change-detection poller + dispatcher     │
 │   types.py · config.py — Pydantic schemas: source of     │
 │                          truth for data + config         │
 │                                                          │
 └──────────────────────────────────────────────────────────┘
                               │
                               ▼
 ┌──────────────────────────────────────────────────────────┐
 │                                                          │
 │   adapter/  MT5Client                                    │
 │   one terminal connection · broker-TZ inference ·        │
 │   type conversions · transparent reinit                  │
 │                                                          │
 └──────────────────────────────────────────────────────────┘
                               │
                               ▼
MetaTrader 5 Python library  →  broker terminal  →  broker server
```

## Contributing

Contributions are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup, test workflow, and project principles.

## License

MIT - see [`LICENSE`](LICENSE).
