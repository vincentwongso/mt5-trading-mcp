# Demo recording

A scripted [asciinema](https://asciinema.org/) terminal recording of a
[Hermes](https://github.com/NousResearch) agent placing **and closing a live
trade** through `mt5-trading-mcp` on Linux — proving the MCP works end-to-end.

![mt5-trading-mcp demo](mt5-mcp-demo.gif)

## Architecture

MT5 and the MCP run **headless inside one Docker container**; the agent on the
host talks to it **over HTTP**. There is no host-side mt5-mcp and no RPyC bridge.

```
┌─ container "mt5-mcp" (ghcr.io/vincentwongso/mt5-trading-mcp:headless) ─┐
│  MT5 terminal (Wine) ─► mt5-mcp (Wine-Python) ─► serves MCP over HTTP  │
│                                       socat ─► 127.0.0.1:8765 (loopback)│
│  KasmVNC web UI (one-time broker login) ─► :3000                       │
└───────────────────────────────────────────────────────────────────────┘
   host -p 127.0.0.1:8765:8765 (MCP)   -p 127.0.0.1:3002:3000 (VNC)
                         ▲
       Hermes agent ── hermes mcp add mt5-mcp --url http://127.0.0.1:8765/mcp
```

## Files

| File | What it is |
|---|---|
| `demo.sh` | The driver. Echoes each command (as if typed) then runs it. The agent step is a real `hermes chat`. |
| `mt5-mcp-demo.cast` | The asciinema recording (real timing). |
| `mt5-mcp-demo.gif` | Rendered GIF (from the cast, via `agg`). |
| `mt5-history.png` | MT5 GUI screenshot — the closed deal in the History tab (manual VNC grab). |
| `config.toml` | DEMO-only `[policy]` override (auto-approve). **Not** a prod template. |

## Dependencies

```bash
asciinema --version    # the recorder            (pip install asciinema  /  uv tool install asciinema)
agg --version          # cast → GIF converter     (https://github.com/asciinema/agg releases)
docker --version       # runs the headless image
hermes --version       # the agent
```

## Preconditions (NOT scripted — set up by hand before recording)

1. **Container up + terminal logged in.**
   `cp deploy/.env.example deploy/.env` (fill broker creds), then
   `docker compose -f deploy/docker-compose.yml up -d`. First boot installs MT5 +
   Wine-Python (a few minutes). Open <http://127.0.0.1:3002> (KasmVNC) once to log
   the terminal into your **demo** account and enable AlgoTrading. Confirm the MCP
   answers: a `ping` tool call over `http://127.0.0.1:8765/mcp` returns `ok: true`.
2. **Agent wired in over HTTP + enabled:**
   `hermes mcp add mt5-mcp --url http://127.0.0.1:8765/mcp`
   (`hermes mcp test mt5-mcp` must print `✓ Connected` + 15 tools), and
   `hermes status` must show a working model/provider.
3. **Auto-approve for a clean one-pass (DEMO ONLY).** The shipped default
   `auto_approve_notional = "0"` makes a 0.01-lot order return an `ApprovalPreview`
   and pause for human confirmation — which stalls an unattended recording. Push
   the demo override into the container's in-Wine config and restart `serve`:

   ```bash
   # path the in-container Wine-Python mt5-mcp reads:
   CFG=/config/.wine/drive_c/users/abc/AppData/Roaming/mt5-mcp/config.toml
   docker exec -u abc mt5-mcp mkdir -p "$(dirname "$CFG")"
   docker exec -i -u abc mt5-mcp sh -c "cat > $CFG" < demo/config.toml
   docker exec mt5-mcp pkill -f 'mt5_mcp serve'   # while-loop in start.sh respawns it
   ```

   The config has no watcher at first boot (none existed to watch), so the
   `pkill` + auto-respawn is what makes `serve` pick it up.
   **Never set a high `auto_approve_notional` in a real deployment.**

## Re-record

```bash
asciinema rec --overwrite --cols 100 --rows 32 -q \
  -c "bash demo/demo.sh" demo/mt5-mcp-demo.cast
agg --theme dracula --font-size 16 --speed 1.3 --idle-time-limit 1.5 \
  --last-frame-duration 4 demo/mt5-mcp-demo.cast demo/mt5-mcp-demo.gif
```

Each render runs `demo.sh` once, which places **one real 0.01-lot round-trip** on
the connected demo account — so re-recording trades again. The cast captures real
agent latency; tune `--speed` / `--idle-time-limit` at the `agg` step, not by
re-recording.

## The GUI screenshot

`mt5-history.png` is a separate manual grab: open the `mt5-mcp` container's VNC web
UI at <http://127.0.0.1:3002>, switch MT5's Toolbox to the **History** tab, and
screenshot the closed deal. (The recording is terminal-only; the screenshot is
extra visual proof that the order really hit the terminal.)

## Safety framing

Demo account only; keep framing experimental, not promotional. The MCP is **not**
the security boundary — the broker enforces hard limits, and the auto-approve here
is a recording convenience, not how you'd run this for real.
