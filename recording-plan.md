# Demo recording plan — agent trades live through mt5-trading-mcp (Linux)

## Goal

A short terminal recording that proves **mt5-trading-mcp works end-to-end on
Linux**: a Hermes agent connects to the headless MT5-in-Docker MCP over HTTP,
places a tiny market order, closes it, and reports the realized P&L — all on a
demo account, captured in one clean GIF.

## Architecture (this is the corrected story)

The earlier draft of this plan targeted an RPyC **bridge** (`pip install
'...[bridge]'`, `[mt5.bridge]`, `backend: bridge`, host-side `mt5linux`). **That
approach was abandoned.** What shipped in v1.2.1 is the all-in-one headless
image (`deploy/`):

```
┌─ Docker container "mt5-mcp" (ghcr.io/vincentwongso/mt5-trading-mcp:headless) ─┐
│  MT5 terminal (Wine)  ──►  mt5-mcp (Wine-Python 3.11)  ──► serves MCP/HTTP    │
│                                          socat ─► 127.0.0.1:8765 (loopback)   │
│  KasmVNC web UI (one-time broker login) ─► :3000                              │
└──────────────────────────────────────────────────────────────────────────────┘
        host  -p 127.0.0.1:8765:8765 (MCP)   -p 127.0.0.1:3002:3000 (VNC)
                              ▲
            Hermes agent (host) ── hermes mcp add --url http://127.0.0.1:8765/mcp
```

The agent talks to the MCP **over HTTP** — there is no host-side mt5-mcp and no
bridge. `mt5-mcp serve` runs *inside* the container.

## Capture: pure asciinema + agg (single tool)

VHS was the original idea, but a live `hermes chat` has variable latency and
every `vhs` re-render would re-run the commands (placing a fresh real trade each
time). asciinema records the real session once at real speed, then `agg`
converts the cast to a GIF. One tool → one consistent look; the trade executes
exactly once.

- `asciinema rec --command "bash demo/demo.sh" demo/mt5-mcp-demo.cast`
- `agg <flags> demo/mt5-mcp-demo.cast demo/mt5-mcp-demo.gif`

## On-camera flow (`demo/demo.sh`)

1. One-line context comment.
2. `docker ps` — the headless `mt5-mcp` container is up (`:8765` MCP, `:3002` VNC).
3. Show how it's wired: `hermes mcp add mt5-mcp --url http://127.0.0.1:8765/mcp`
   (registered once; `hermes mcp test mt5-mcp` confirms HTTP + 15 tools).
4. **The star:** `hermes chat -q '<round-trip prompt>'` — the agent, with tool
   previews visible, calls `get_account_info` + `get_quote`, **places a 0.01-lot
   market BUY on EURUSD.z**, shows the open position, **closes it**, then reports
   realized P&L from `get_history` and the new balance.
5. Closing comment pointing at the MT5 GUI screenshot.

## Preconditions (NOT scripted — set up by hand before recording)

1. **Container up + terminal logged in.** `cp deploy/.env.example deploy/.env`
   (fill broker creds), `docker compose -f deploy/docker-compose.yml up -d`.
   First boot installs MT5 + Wine-Python (minutes). Log the terminal into your
   **demo** account once at <http://127.0.0.1:3002> (KasmVNC), enable AlgoTrading.
2. **MCP reachable:** the loopback HTTP endpoint answers (`ping` → `ok: true`).
3. **Hermes can reach a model** (`hermes status` shows a working provider).
4. **Auto-approve for a clean one-pass** (demo only): the shipped default
   `auto_approve_notional = 0` makes the policy engine return an `ApprovalPreview`
   and pause for human confirmation — which stalls an unattended recording. The
   recording setup writes a `[policy] auto_approve_notional` high into the
   container's config so the tiny order executes in one pass. **Never do this in
   a real deployment** — keep the gate low so a human confirms material trades.

## Result proof

- **In-terminal:** the agent reports ticket, close, realized P&L, new balance.
- **MT5 GUI screenshot:** `demo/mt5-history.png` — the closed deal in MT5's
  History tab, grabbed from the VNC web UI (`http://127.0.0.1:3002`).

## Safety framing

- Demo account only; keep framing experimental, not promotional.
- The MCP is **not** the security boundary — the broker enforces hard limits.
  Auto-approve here is a recording convenience, called out as such.

## Deliverables

- `demo/demo.sh` — the reproducible driver.
- `demo/mt5-mcp-demo.cast` + `demo/mt5-mcp-demo.gif` — the recording.
- `demo/mt5-history.png` — the MT5 GUI proof shot.
- `demo/README.md` — deps, the architecture, and the re-record command.
