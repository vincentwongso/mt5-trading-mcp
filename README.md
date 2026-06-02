# mt5-mcp

**Let an AI agent read your MetaTrader 5 account and place real trades over the [Model Context Protocol](https://modelcontextprotocol.io) - behind a preflight + human-consent + append-only-audit safety layer.**

[![PyPI version](https://img.shields.io/pypi/v/mt5-trading-mcp.svg)](https://pypi.org/project/mt5-trading-mcp/)
[![PyPI downloads](https://img.shields.io/pypi/dm/mt5-trading-mcp.svg)](https://pypi.org/project/mt5-trading-mcp/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/mt5-trading-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/vincentwongso/mt5-trading-mcp/test.yml?branch=main&label=tests)](https://github.com/vincentwongso/mt5-trading-mcp/actions/workflows/test.yml)
[![GitHub stars](https://img.shields.io/github/stars/vincentwongso/mt5-trading-mcp?style=flat&label=stars)](https://github.com/vincentwongso/mt5-trading-mcp/stargazers)

<p align="center">
  <img src="https://raw.githubusercontent.com/vincentwongso/mt5-trading-mcp/main/demo/mt5-mcp-demo.gif" width="600" alt="mt5-mcp demo: an AI agent places and closes a live trade over MCP"><br>
  <sub>A <a href="https://github.com/NousResearch">Hermes</a> agent placing then closing a real 0.01-lot trade on a <b>demo</b> account, end-to-end over MCP on Linux.</sub>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/vincentwongso/mt5-trading-mcp/main/demo/mt5-history.png" width="820" alt="The same round-trip in MetaTrader 5's History tab"><br>
  <sub>Not a mock-up - the same round-trip in MetaTrader 5's own History tab; the tickets and balance match the recording.</sub>
</p>

> ⚠️ **This software places _real_ trades through your MetaTrader 5 terminal with
> real orders and irreversible fills.** Read
> [DISCLAIMER.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/DISCLAIMER.md)
> and [SECURITY.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/SECURITY.md)
> before connecting it to a live account. Always test using your demo account first.

Runs locally - in the same process tree as your agent, no cloud, no telemetry.
Windows (native) or Linux (via Docker); Python 3.10+.

## What it is

`mt5-mcp` lets an AI agent read your MetaTrader 5 account and place trades
through it, over the Model Context Protocol.

- **11 read-only tools**: account, quotes, positions, orders, history, OHLC
  bars, and broker-authoritative margin estimates. No consent gate.
- **4 mutating tools**: `place_order`, `modify_order`, `cancel_order`,
  `close_position`, each behind a preflight + human-consent + idempotency +
  audit layer.
- **3 subscribable resources**: live `account://`, `positions://`, and
  `quotes://{symbol}` snapshots that push change notifications.
- **2 ready-to-use Claude Code skills** ship in
  [`.claude/skills/`](https://github.com/vincentwongso/mt5-trading-mcp/tree/main/.claude/skills):
  `mt5-market-data` and `mt5-trading` teach an agent how to read the account and
  run the consent flow safely.

Full catalogue and the consent flow: **[docs/tools.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/tools.md)**.

## Why mt5-mcp

- **A safety layer, not just an API wrapper.** Every mutating call routes through
  preflight checks → a fail-closed human-consent gate (every order needs approval
  by default) → idempotency → an append-only audit log, so an agent can't quietly
  fire-and-forget irreversible orders.
- **An honest threat model.** It treats an LLM wired to `place_order` as a live
  attack surface and says so plainly - the MCP is explicitly *not* the security
  boundary (see [SECURITY.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/SECURITY.md)).
- **Verifiable proof, not a mock-up.** The demo above is a real round-trip; the
  tickets and balance match MetaTrader 5's own History tab.
- **Local-first.** No cloud, no telemetry; runs beside your agent. Windows-native
  or Linux via an all-in-one Docker image (no `rpyc` version-matching).

## Quickstart (Windows, native)

```bash
pip install mt5-trading-mcp
```

1. Launch MetaTrader 5 and log into your broker. Enable **AlgoTrading** (toolbar
   button green).
2. Verify the terminal is reachable: `python -m mt5_mcp doctor`: expect
   `[INFO] backend: native` and `[PASS]` lines.
3. Run it: `python -m mt5_mcp serve`.

## Quickstart (Linux, Docker)

The MT5 terminal + the MCP run headless in an all-in-one image; your agent talks
MCP over HTTP. No host Python, no bridge.

```bash
cp deploy/.env.example deploy/.env   # add MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
docker compose -f deploy/docker-compose.yml up -d
```

Log the terminal in once via the KasmVNC web UI at `http://127.0.0.1:3001`
(**File → Login to Trade Account**; persists across restarts), then point your
agent at `http://127.0.0.1:8765/mcp`. Full walkthrough:
**[docs/installation.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/installation.md)**.

## For AI agents

**If you've been handed this repository to install and run, follow the runbook
in [docs/agents.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/agents.md).**
It covers platform detection, install, verification, registering the server, and
the hard safety rules for trades - read it before calling any mutating tool.

## Documentation

| Guide | What's in it |
|---|---|
| [Installation & setup](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/installation.md) | Requirements, Windows + Linux/Docker setup, wiring to an agent. |
| [For AI agents](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/agents.md) | Step-by-step runbook for an agent installing and running the server. |
| [Configuration](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/configuration.md) | `config.toml` schema, storage paths, hot-reload. |
| [Tools & resources](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/tools.md) | Read tools, mutating tools + consent flow, subscribable resources. |
| [MCP client setup](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/clients.md) | Per-client config snippets and Claude Code usage. |
| [Transports & deployment](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/docs/deployment.md) | stdio/HTTP transports and Windows VPS patterns. |
| [Contributing](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/CONTRIBUTING.md) | How to contribute and run the tests. |
| [Changelog](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/CHANGELOG.md) | Release history and known limitations. |

## Safety

`mt5-mcp` is **not** the security boundary, the broker's MT5 server enforces
the hard limits (margin, max-lot, symbol permissions). Pre-flight checks in the
policy engine are UX guardrails to catch agent mistakes early, not security
controls.

The human-consent gate is **fail-closed by default**: `auto_approve_notional`
defaults to `0`, so **every mutating call requires explicit human approval** (an
`ApprovalPreview` you confirm) before it executes. Raise the threshold to
auto-approve orders below a notional you trust; orders that widen stops always
require approval. Every mutating call is recorded in an append-only audit JSONL
log regardless. For vulnerability disclosure, see
[SECURITY.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/SECURITY.md).

## Architecture

`mt5-mcp` wraps the MetaTrader 5 Python library behind a FastMCP server. A single `MT5Client` (`src/mt5_mcp/adapter/`) owns the terminal connection, broker-timezone inference, and type conversions; everything else sits on top of it. The Pydantic models in `src/mt5_mcp/types.py` / `src/mt5_mcp/config.py` are the source of truth for the data and config schemas.

```
     Agent / MCP client  (Hermes, OpenClaw, Claude Code, Claude Desktop, …)
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
 │   streaming/  - change-detection poller + dispatcher     │
 │   types.py · config.py - Pydantic schemas: source of     │
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

The module paths shown (`tools/`, `resources/`, `policy/`, `streaming/`,
`adapter/`, `types.py`, `config.py`) all live under `src/mt5_mcp/`.

## Contributing

Contributions are welcome, see
[CONTRIBUTING.md](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/CONTRIBUTING.md)
for the dev setup, test workflow, and project principles.

## License

MIT - see [`LICENSE`](https://github.com/vincentwongso/mt5-trading-mcp/blob/main/LICENSE).
