# Installation & setup

[← Back to README](../README.md)

## Requirements

- **Windows** (native) — the `MetaTrader5` library runs in-process; or
- **Linux** — an all-in-one Docker image runs the MT5 terminal **and** the
  server, reachable over HTTP (see
  [Linux](#linux--all-in-one-docker-image-recommended)). A host-side RPyC bridge
  remains available as an alternative.
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

### Linux — all-in-one Docker image (recommended)

One image runs the MT5 terminal under Wine, a KasmVNC web UI for a one-time
login, and `mt5-mcp` serving MCP over HTTP. No host Python, no bridge, no
`rpyc` version-matching.

1. **Credentials.** Copy [`deploy/.env.example`](../deploy/.env.example) to
   `deploy/.env` and fill in `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`. The
   password is read **only** from the environment — it is never written to a
   config file or logged. To keep it out of a file entirely, inject it at
   runtime instead, e.g. with 1Password:
   ```
   op run -- docker compose -f deploy/docker-compose.yml up -d
   ```
2. **Start it:**
   ```
   docker compose -f deploy/docker-compose.yml up -d
   ```
   First boot installs MetaTrader 5 + 64-bit Wine-Python into the container's
   volume — a few minutes. (If MT5's installer fails with `socket: Function not
   implemented`, restart the container.)
3. **Log the terminal in once.** Open `http://127.0.0.1:3001` (KasmVNC; web auth
   is `VNC_USER`/`VNC_PASSWORD` from `.env`) and choose **File → Login to Trade
   Account**. The login persists in the `mt5-mcp-config` volume, so every
   restart afterward is headless.
   > A cold programmatic login isn't reliable under Wine, so this one-time VNC
   > login is required. After it, the server attaches on its own (using the
   > credentials) and re-attaches automatically on restart.
4. **Connect your agent** to `http://127.0.0.1:8765/mcp` (loopback only).
   Health-check with `docker logs mt5-mcp` (look for `Uvicorn running` and a
   successful connect); your agent's first `ping` returns `ok: true`.

Ports are overridable via `MCP_PORT` (default `8765`) and `VNC_PORT` (default
`3001`). The published image is
`ghcr.io/vincentwongso/mt5-trading-mcp:headless` — `docker compose pull` fetches
it. The commands above use it as-is; add `--build` only when you've modified
`deploy/` locally and want Compose to rebuild the image instead.

> **Symbol names are broker-specific.** Some brokers suffix instruments — e.g.
> `EURUSD.z`, `XAUUSD.z` (crypto such as `BTCUSD` is often unsuffixed). Always
> use the exact name returned by `get_symbols`; a bare `EURUSD` may come back
> `SYMBOL_NOT_FOUND`.

### Linux — host-side bridge (alternative)

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
   `~/.config/mt5-mcp/config.toml` and uncomment the `[mt5.bridge]` block
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

Register the server with your agent harness. **Transport depends on the setup:**
the all-in-one Docker image already serves MCP over **HTTP** — point the harness
at `http://127.0.0.1:8765/mcp`. Windows-native and the bridge backend run over
**stdio** (`python -m mt5_mcp serve`).

[`examples/clients/hermes.json`](../examples/clients/hermes.json) shows a Hermes
`mcp_servers` block scoped to the **read-only** tools via `include` (so the
agent can't trade until you widen it). Claude Code, Codex, OpenClaw, Claude
Desktop (HTTP + stdio), and Cursor have configs under
[`examples/clients/`](../examples/clients/); see
[MCP client setup](clients.md) for the per-client details.

## Next steps

- [Configuration](configuration.md) — `config.toml` schema and storage paths.
- [Tools & resources](tools.md) — what the agent can actually call.
- [MCP client setup](clients.md) — per-client config snippets.
- [Transports & deployment](deployment.md) — HTTP transport and Windows VPS patterns.
