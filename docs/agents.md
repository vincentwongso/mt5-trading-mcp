# For AI agents - installing & running mt5-mcp

**If you are an AI agent that has been handed this repository to install and
run, follow this procedure.**

1. **Detect the platform and pick a backend.** Windows runs the `MetaTrader5`
   library natively; Linux runs the terminal in an all-in-one Docker image (the
   agent talks MCP over HTTP). Full per-platform steps:
   **[docs/installation.md](installation.md)**.
2. **Install from this checkout:**
   - **Windows:** `pip install .` (or `uv sync --extra dev`). Tell the human to
     launch MetaTrader 5, log into their broker, and enable **AlgoTrading**.
   - **Linux (recommended):** bring up the Docker image - creds in
     `deploy/.env`, then `docker compose -f deploy/docker-compose.yml up -d`
     (it uses the published image; add `--build` only for local `deploy/`
     changes). The server runs in the container and serves MCP over HTTP; the
     one-time VNC login + bridge alternative are in `docs/installation.md`.
3. **Verify before doing anything else:** Windows -> `python -m mt5_mcp doctor`
   (expect the backend + `[PASS]` lines); Docker image -> after the human's
   one-time VNC login, your first `ping` returns `ok: true`. Do **not** proceed
   if verification fails - report it to the human and stop.
4. **Register / run the server:** Docker image -> it's already serving; register
   `http://127.0.0.1:8765/mcp`. Windows -> `python -m mt5_mcp serve` (stdio) with
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
   on a demo assumption - confirm it's a demo account first.

Tool semantics and the full consent flow: **[docs/tools.md](tools.md)**.
Under Claude Code, cloning this repo auto-loads the `.claude/skills/`
(market-data, trading, and mql5-build); you register the MCP server yourself (one
`claude mcp add` command) - see **[docs/clients.md](clients.md)** for how that
fits together.

## Building MQL5 (EAs, indicators, scripts)

Asked to write or fix MQL5? Use `mt5-mcp compile <file.mq5>` on the machine
that runs MetaTrader 5 (Windows) and follow the `mt5-mql5-build` skill:
compile, fix each `file:line:col` error, repeat until exit code `0`. Exit code
`2` is a setup problem (MetaEditor or data folder not found, timeout) - report
it, do not edit the code. **Never attach or start an EA yourself, and ask
before rebuilding one the human says is running on a live chart** (MT5 reloads
it).

Linux/Docker: run both commands in the backtest container from
`deploy/docker-compose.backtest.yml` (MT5 under Wine, no MCP server, CPUs
limited so the live container keeps headroom):
`docker exec mt5-backtest mt5-mcp compile|backtest ...` with host paths inside
the shared work folder (`MT5_WORK_DIR`, mounted at the same path). Setup:
fill `deploy/.env.backtest` from the example, `docker compose -f
deploy/docker-compose.backtest.yml --env-file deploy/.env.backtest up -d`, log
the terminal in once (VNC on `VNC_PORT`), then
`docker exec mt5-backtest mt5-mcp backtest --setup`. Use `--out <work>/out` to
get the report and JSON on the host.

To test an EA, use `mt5-mcp backtest` (Windows, same skill): run
`mt5-mcp backtest --setup` once, then
`mt5-mcp backtest <installed .ex5> --symbol ... --period H1 --from ... --to ...`.
It runs on a separate copy of MT5, never the live terminal. `--optimize
full|genetic` with a `.set` file of `Name=value||start||step||stop||Y` lines
ranks input sets, scored on a held-out forward period by default. Exit `0`
finished, `2` could not run. `--wait` queues behind a running backtest; after
an MT5 update the tester copy refreshes itself. Supported from a logged-in desktop session;
over ssh it also worked in testing (including the 1.8.0 end-to-end run), but
that is best effort. The tester copy is logged into the user's own account,
possibly real money, with algo trading switched off for every run; the
terminal language must be English. The EA's `Print` output lands in the tester
folder under `Tester\Agent-*\logs\`; each run also writes a JSON file
(printed as `json:`, or to stdout with `--json`) with every deal, the balance
curve, drawdown periods and that run's log lines. A single run whose EA fails
to start or crashes exits `2`. A good backtest
is never a reason to attach the EA live: report it to the human.
