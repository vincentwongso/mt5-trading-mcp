# Transports & deployment

[<- Back to README](../README.md)

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

Constraints (current release):

- **Loopback-only** (`127.0.0.1`, `::1`, `localhost`). Binding to any other
  address raises a startup error. Direct LAN/internet exposure is intentionally
  not supported; see [Deploying to a Windows VPS](#deploying-to-a-windows-vps)
  below for the secure alternative.
- **Optional bearer-token authentication** via `transport.http.auth_token` in
  `config.toml`. When set, every request must carry
  `Authorization: Bearer <token>`. Comparison is constant-time. **Leaving it
  empty means the (loopback) server is unauthenticated - any local process can
  place real trades; the server logs a warning at startup.** Set a token whenever
  the HTTP transport is reachable beyond a single trusted user.
- Uses the `streamable-http` FastMCP transport under the hood, which supports
  both request/response and SSE streaming on a single endpoint.

Default port: `8765` (configurable via `[transport.http] port`).

## Deploying to a Windows VPS

Common case: you want your MT5 terminal running 24/7 on a server, but laptops
sleep. Two supported patterns:

### Pattern A - Agent + MCP both on the VPS

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
  trigger of "At log on" to launch MT5. "At system startup" alone won't work -
  MT5 needs a logged-in user.
- The `config.toml` watchdog hot-reload still works - just edit the file on the
  VPS.

### Pattern B - Agent local, MCP on the VPS via SSH tunnel

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

Now `http://localhost:8765/mcp` on your laptop reaches the MCP on the VPS -
without ever exposing the HTTP port to the public internet. Use the
[`claude-desktop-http.json`](../examples/clients/claude-desktop-http.json)
example to register it with Claude Desktop.

This is the secure default for remote MT5 terminals. Direct non-loopback HTTP
binding is intentionally **not** supported - it would require a TLS
termination story and tighter auth than a single bearer token. If you need it
for a real deployment, please open an issue describing the use case.

### Keeping `mt5-mcp serve` running

For Pattern A's HTTP transport or Pattern B's VPS-side server, you'll want the
process to survive reboots:

- **NSSM** ([Non-Sucking Service Manager](https://nssm.cc/)) is the lightest
  option - wrap `python -m mt5_mcp serve --transport http` as a Windows Service.
- A scheduled task triggered **at logon** with a restart-on-failure policy works
  too. [`examples/vps/install-mt5-mcp-task.ps1`](../examples/vps/install-mt5-mcp-task.ps1)
  registers one for you, and also installs an optional companion task that
  restarts the server once a day (`-DailyRestartAt`, default `03:30`).

`mt5-mcp` doesn't bundle a service wrapper; pick the one your ops setup already
uses.

> **Why "at logon", not "at system startup"?** The MetaTrader5 Python library
> only talks to a terminal running in the **same interactive desktop session**,
> so the server can't run as a Session 0 Windows Service / "at system startup"
> task. It must start after a user logs on - which means surviving an unattended
> reboot requires **Windows auto-logon** so the box logs the user in
> automatically and the logon trigger fires.

#### One-shot setup wrapper

[`examples/vps/setup-vps.ps1`](../examples/vps/setup-vps.ps1) does the whole VPS
setup in one idempotent, elevated run: install/upgrade the package into a venv,
register the auto-start + daily-restart tasks (via `install-mt5-mcp-task.ps1`),
drop a Startup-folder shortcut so the MT5 terminal launches at logon, optionally
configure auto-logon (`-EnableAutoLogon`, prompts for the password), then verify
the task is running and the port is up.

```powershell
# elevated PowerShell, from examples/vps/
powershell -ExecutionPolicy Bypass -File .\setup-vps.ps1 -EnableAutoLogon
```

Use `-VenvPath` / `-WorkingDirectory` / `-TerminalPath` for non-default layouts,
`-SkipInstall` to leave pip alone, and `-Uninstall` to remove the tasks and
shortcut. `-EnableAutoLogon` uses the registry method, which stores the password
in plaintext under `HKLM\...\Winlogon`; for encrypted storage prefer
[Sysinternals Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon)
and omit the switch.

### HTTP memory & log noise

A long-running HTTP server polled around the clock can creep up in memory and
spam its console with one log line per request. Both are handled by defaults
since the leak fix: stateless HTTP (`[transport.http] stateless = true`) stops
the per-session transport accumulation, and a `WARNING` default log level keeps
the console quiet. See
[Configuration → HTTP memory & logging](configuration.md#http-memory--logging)
for the full rundown and the daily-restart safety net.
