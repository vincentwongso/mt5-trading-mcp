#!/usr/bin/env bash
#
# Demo driver for the mt5-trading-mcp recording. Recorded with asciinema:
#
#   asciinema rec --command "bash demo/demo.sh" demo/mt5-mcp-demo.cast
#   agg demo/mt5-mcp-demo.cast demo/mt5-mcp-demo.gif
#
# PRECONDITIONS (see demo/README.md — these are NOT scripted):
#   * The all-in-one "mt5-mcp" container is up, terminal logged into a DEMO
#     account, MCP answering on http://127.0.0.1:8765/mcp.
#   * mt5-mcp is registered with Hermes over HTTP and ENABLED:
#       hermes mcp add mt5-mcp --url http://127.0.0.1:8765/mcp
#   * Hermes can reach a model (hermes status).
#   * Container config has a high [policy] auto_approve_notional (DEMO ONLY) so
#     the tiny order auto-executes instead of pausing for human confirmation.
set -u

GREEN='\033[1;32m'; DIM='\033[2m'; RST='\033[0m'

say()  { printf "${DIM}%s${RST}\n" "$*"; sleep 1.2; }          # narration comment
run()  { printf "${GREEN}\$${RST} %s\n" "$*"; sleep 0.7; eval "$@"; sleep 1.6; }  # show + run

# The agent's instruction. Explicit on symbol (.z suffix), volume and ordering
# so a small/fast model drives the full round-trip reliably.
read -r -d '' PROMPT <<'EOP'
This is a DEMO account — don't ask me for confirmation, just do it. Using the
mt5-mcp tools, in order: (1) report my account balance; (2) get the EURUSD.z
quote; (3) place a market BUY of 0.01 lots of EURUSD.z; (4) show the resulting
open position (ticket + open price); (5) close that position fully; (6) report
the round-trip realized P&L and my new balance. Use the exact symbol "EURUSD.z"
and keep each step concise.
EOP

clear
say "# mt5-trading-mcp on Linux — MT5 + the MCP run headless in Docker;"
say "# a Hermes agent drives them over HTTP. Watch one live round-trip on a demo account."
sleep 0.4

say ""
say "# 1) The headless MT5 + MCP container is already running:"
run "docker ps --filter name=mt5-mcp --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

say ""
say "# 2) It's wired into the agent over HTTP (one-time setup):"
say "#      hermes mcp add mt5-mcp --url http://127.0.0.1:8765/mcp"
run "hermes mcp test mt5-mcp"

say ""
say "# 3) Now let the agent run the whole round-trip — the MCP tool calls are live:"
printf "${GREEN}\$${RST} hermes chat -q '%s'\n" "place 0.01 EURUSD.z, close it, report the P&L"
sleep 0.8
hermes chat -q "$PROMPT"

say ""
say "# Placed → closed → P&L reported, end-to-end through mt5-trading-mcp."
say "# Filled order in the MT5 GUI (History tab): see demo/mt5-history.png"
sleep 1.5
