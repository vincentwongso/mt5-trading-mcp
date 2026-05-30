# Transports & deployment

[← Back to README](../README.md)

## Transports

### stdio (default)

`python -m mt5_mcp` and `python -m mt5_mcp serve` both run in stdio mode. This is
the correct choice for Claude Desktop, Cursor, and any agent runtime that
manages the server as a subprocess.

### HTTP (opt-in)

For agent runtimes that prefer a long-running HTTP server instead of a
subprocess:

```bash
python -m mt5_mcp serve --transport http
```

Constraints in v1.0:

- **Loopback-only** (`127.0.0.1`, `::1`, `localhost`). Binding to any other
  address raises a startup error. Direct LAN/internet exposure is intentionally
  not supported in v1.0; see [Deploying to a Windows VPS](#deploying-to-a-windows-vps)
  below for the secure alternative.
- **Optional bearer-token authentication** via `transport.http.auth_token` in
  `config.toml`. When set, every request must carry
  `Authorization: Bearer <token>`. Comparison is constant-time.
- Uses the `streamable-http` FastMCP transport under the hood, which supports
  both request/response and SSE streaming on a single endpoint.

Default port: `8765` (configurable via `[transport.http] port`).

## Deploying to a Windows VPS

Common case: you want your MT5 terminal running 24/7 on a server, but laptops
sleep. Two supported patterns:

### Pattern A — Agent + MCP both on the VPS

Simplest setup. RDP into the VPS, install Python and the MetaTrader 5 terminal,
then:

```powershell
pip install mt5-trading-mcp
python -m mt5_mcp doctor   # verify the terminal is reachable
```

Run your MCP client (Claude Desktop, Cursor, or another) on the VPS itself and
register `mt5-mcp` via the stdio config snippet. The agent's context lives on
the VPS.

Practical notes:

- The MT5 terminal needs an active Windows desktop session to connect to the
  broker, so on an unattended VPS you'll want auto-logon configured at the OS
  level (your VPS provider's docs cover this) plus a Windows Task Scheduler
  trigger of "At log on" to launch MT5. "At system startup" alone won't work —
  MT5 needs a logged-in user.
- The `config.toml` watchdog hot-reload still works — just edit the file on the
  VPS.

### Pattern B — Agent local, MCP on the VPS via SSH tunnel

Use this when you want your agent running on your laptop but the MT5 terminal on
the VPS.

On the VPS, run the HTTP transport (loopback-bound):

```powershell
python -m mt5_mcp serve --transport http
```

On your local machine, open an SSH tunnel that forwards the loopback port:

```bash
ssh -L 8765:localhost:8765 user@vps-host
```

Now `http://localhost:8765/mcp` on your laptop reaches the MCP on the VPS —
without ever exposing the HTTP port to the public internet. Use the
[`claude-desktop-http.json`](../examples/clients/claude-desktop-http.json)
example to register it with Claude Desktop.

This is the secure default for remote MT5 terminals. Direct non-loopback HTTP
binding is intentionally **not** supported in v1.0 — it would require a TLS
termination story and tighter auth than a single bearer token. If you need it
for a real deployment, please open an issue describing the use case.

### Keeping `mt5-mcp serve` running

For Pattern A's HTTP transport or Pattern B's VPS-side server, you'll want the
process to survive reboots:

- **NSSM** ([Non-Sucking Service Manager](https://nssm.cc/)) is the lightest
  option — wrap `python -m mt5_mcp serve --transport http` as a Windows Service.
- A scheduled task with "At system startup" + a restart-on-failure policy works
  too.

`mt5-mcp` doesn't bundle a service wrapper; pick the one your ops setup already
uses.
