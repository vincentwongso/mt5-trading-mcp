# Installation & setup

[← Back to README](../README.md)

## Requirements

- **Windows** (native) — the `MetaTrader5` library runs in-process; or
- **Linux** — the MT5 terminal runs in Docker (Wine) and `mt5-trading-mcp`
  connects to it over RPyC (see [Linux](#linux-mt5-in-docker-bridge-backend)).
- Python 3.10 or newer.
- A running MetaTrader 5 terminal logged into a broker (native on Windows, or
  in the container on Linux).

## Install

From PyPI:

```bash
pip install mt5-trading-mcp
```

Or with [`uv`](https://docs.astral.sh/uv/):

```bash
uv pip install mt5-trading-mcp
```

> The PyPI distribution is `mt5-trading-mcp`, but the CLI command, Python module
> (`mt5_mcp`), and project brand are still `mt5-mcp`. The short name was already
> taken on PyPI by an unrelated project.

### From source (for contributors)

```bash
git clone https://github.com/vincentwongso/mt5-trading-mcp.git
cd mt5-trading-mcp
uv sync --extra dev
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full development workflow.

## Setup

`mt5-trading-mcp` needs a MetaTrader 5 terminal it can reach. Pick your OS.

### Windows (native)

1. Install MetaTrader 5 and log into your broker. Enable **AlgoTrading**
   (toolbar button green).
2. Install the server:
   ```
   pip install mt5-trading-mcp
   ```
3. No extra config needed (native backend is the default).
4. Verify:
   ```
   python -m mt5_mcp doctor
   ```
   Expect `[INFO] backend: native` and `[PASS]` lines. Then run
   `python -m mt5_mcp serve`.

### Linux (MT5 in Docker, bridge backend)

The MT5 terminal runs in a Wine container; the server connects over RPyC.

1. Start the terminal container (compose file in
   [`examples/docker-compose.yml`](../examples/docker-compose.yml)):
   ```
   docker compose -f examples/docker-compose.yml up -d
   ```
   Open `http://localhost:3000` (KasmVNC) and finish the MT5 install + broker
   login. First boot can take a few minutes; if MT5 fails to install with
   `socket: Function not implemented`, restart the container.
2. Install the server with the bridge client:
   ```
   pip install 'mt5-trading-mcp[bridge]'
   ```
3. Configure the bridge — copy
   [`examples/config.toml.example`](../examples/config.toml.example) to
   `~/.config/mt5-mcp/config.toml` and keep the `[mt5.bridge]` block
   (`host = "127.0.0.1"`, `port = 8001`).
4. Verify:
   ```
   python -m mt5_mcp doctor
   ```
   Expect `[INFO] backend: bridge → 127.0.0.1:8001` and `[PASS]` lines.

   **Bridge version note:** the host's `mt5linux`/`rpyc` must be
   protocol-compatible with the container's RPyC server. The stock image ships
   `mt5linux 1.0.3` (which pins `rpyc==5.2.3`); if the server fails to start with
   `Unknown switch -w`, pin a matching `rpyc` or use the maintained
   `MT5LinuxEnhanced` client.

### Wire it to an agent

Register the server with your agent harness.
[`examples/clients/hermes.json`](../examples/clients/hermes.json) shows a Hermes
`mcp_servers` block scoped to the **read-only** tools via `include` (so the
agent can't trade until you widen it). Claude Code, Codex, OpenClaw, Claude
Desktop, and Cursor have configs under
[`examples/clients/`](../examples/clients/); see
[MCP client setup](clients.md) for the per-client details.

## Next steps

- [Configuration](configuration.md) — `config.toml` schema and storage paths.
- [Tools & resources](tools.md) — what the agent can actually call.
- [MCP client setup](clients.md) — per-client config snippets.
- [Transports & deployment](deployment.md) — HTTP transport and Windows VPS patterns.
