# For AI agents — installing & running mt5-mcp

**If you are an AI agent that has been handed this repository to install and
run, follow this procedure.**

1. **Detect the platform and pick a backend.** Windows runs the `MetaTrader5`
   library natively; Linux runs the terminal in an all-in-one Docker image (the
   agent talks MCP over HTTP). Full per-platform steps:
   **[docs/installation.md](installation.md)**.
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
   a config under [`examples/clients/`](../examples/clients/) (e.g.
   [`hermes.json`](../examples/clients/hermes.json)) that scopes you to the
   read-only tools by default.
5. **Operate read-only unless explicitly asked to trade.** The read tools are
   safe to call freely.
6. **⚠️ Hard rule, if live account and using real money.** `place_order`,
   `modify_order`, and `close_position` execute **real, irreversible trades**.
   When one returns an `ApprovalPreview`, show it **verbatim** to the human and
   only retry with `approval_confirmed=true` after they explicitly approve
   **that specific order**. Never auto-confirm, never batch-approve, never trade
   on a demo assumption — confirm it's a demo account first.

Tool semantics and the full consent flow: **[docs/tools.md](tools.md)**.
Under Claude Code, cloning this repo wires up the MCP server (`.mcp.json`) and
auto-loads the `.claude/skills/` (market-data + trading) — see
**[docs/clients.md](clients.md)** for how that fits together.
