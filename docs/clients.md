# MCP client setup

[<- Back to README](../README.md)

Drop-in config snippets are in
[`examples/clients/`](../examples/clients/):

- **Hermes (Nous Research):** [`hermes.json`](../examples/clients/hermes.json) -
  a direct `mcp_servers` block with the read-only tools `include`-scoped (the
  launch/demo agent). See [Installation -> Wire it to an agent](installation.md#wire-it-to-an-agent).
- **Claude Code:** [`claude-code.json`](../examples/clients/claude-code.json) -
  register the server with `claude mcp add --scope project mt5-mcp -- python -m
  mt5_mcp serve` (or save the snippet as `.mcp.json` in your project), then
  read-only-scope it by allowlisting the eleven read tools in
  `.claude/settings.json` (`mcp__mt5-mcp__<tool>`). Cloning this repo auto-loads
  the project-scoped skills under `.claude/skills/`; you register the server and
  add the read-only allowlist yourself - see
  [Using with Claude Code](#using-with-claude-code).
- **Codex (OpenAI Codex CLI):** [`codex.toml`](../examples/clients/codex.toml) -
  a `[mcp_servers.mt5-mcp]` table for `~/.codex/config.toml`. Add it with
  `codex mcp add mt5-mcp -- python -m mt5_mcp serve`; the file shows the
  `enabled_tools` allowlist that scopes the agent to the read-only tools (or
  `default_tools_approval_mode = "prompt"` to human-confirm the mutating ones).
- **OpenClaw:** [`openclaw.json`](../examples/clients/openclaw.json) - an
  `mcp.servers` entry for `~/.openclaw/openclaw.json` (note: `mcp.servers`,
  **not** `mcpServers`). OpenClaw has no per-server read-only filter, so the
  mutating tools stay gated by mt5-mcp's own consent engine; the file header
  notes the `gateway.tools.deny` and separate-read-only-instance options.
- **Claude Desktop, stdio:**
  [`claude-desktop-stdio.json`](../examples/clients/claude-desktop-stdio.json).
  Paste the inner `mcpServers` entry into
  `%APPDATA%\Claude\claude_desktop_config.json`.
- **Claude Desktop, HTTP:**
  [`claude-desktop-http.json`](../examples/clients/claude-desktop-http.json).
  For when `mt5-mcp serve --transport http` is already running.
- **Cursor:** [`cursor.json`](../examples/clients/cursor.json). Paste into
  `~/.cursor/mcp.json`.

If `python` isn't on PATH (or you want to pin a specific venv), substitute the
absolute path:

```json
{
  "mcpServers": {
    "mt5-mcp": {
      "command": "C:\\Users\\<you>\\.venvs\\mt5-mcp\\Scripts\\python.exe",
      "args": ["-m", "mt5_mcp", "serve"]
    }
  }
}
```

## Using with Claude Code

Cloning the repo auto-loads the project-scoped skills:

```
.claude/skills/
├── mt5-market-data/SKILL.md   # what each read tool does + output conventions
└── mt5-trading/SKILL.md       # consent flow, idempotency, error taxonomy, demo framing
```

The MCP server itself is not committed - register it yourself from the repo root:

```
claude mcp add --transport stdio --scope project mt5-mcp -- python -m mt5_mcp serve
```

To scope the agent to read-only, create a `.claude/settings.json` that
allowlists the eleven read tools (the mutating tools stay un-allowlisted, so
they prompt per call):

```json
{
  "permissions": {
    "allow": [
      "mcp__mt5-mcp__ping",
      "mcp__mt5-mcp__get_terminal_info",
      "mcp__mt5-mcp__get_account_info",
      "mcp__mt5-mcp__get_quote",
      "mcp__mt5-mcp__get_symbols",
      "mcp__mt5-mcp__get_market_hours",
      "mcp__mt5-mcp__get_rates",
      "mcp__mt5-mcp__calc_margin",
      "mcp__mt5-mcp__get_positions",
      "mcp__mt5-mcp__get_orders",
      "mcp__mt5-mcp__get_history"
    ]
  }
}
```

**To use:**

1. Clone the repo and install the package into the Python that Claude Code will
   spawn (`uv sync --extra dev` from the repo root, or
   `pip install mt5-trading-mcp` system-wide). **Linux:** the recommended path is
   the all-in-one Docker image, which serves MCP over HTTP - register that
   transport instead of the stdio server (see
   [Installation -> Linux (Docker)](installation.md#linux---all-in-one-docker-image-recommended)).
   The host-side RPyC bridge (`pip install 'mt5-trading-mcp[bridge]'` +
   `[mt5.bridge]`) remains an
   [alternative](installation.md#linux---host-side-bridge-alternative).
2. Register the server (it is not committed): from the repo root, run
   `claude mcp add --transport stdio --scope project mt5-mcp -- python -m mt5_mcp serve`.
3. Launch the MT5 terminal and log into your broker.
4. From the repo root, run `claude`. Confirm `mt5-mcp` shows up under `/mcp`.
5. Ask the agent something like *"what's my account balance"* or *"show me the
   price of EURUSD"*. With the read-only allowlist above in place, the read
   tools fire without a permission prompt (otherwise Claude Code asks once per
   tool); the `mt5-market-data` skill teaches the agent how to interpret the
   output.
6. Asking the agent to **place, modify, or close** a trade hits an interactive
   permission prompt (defence in depth above the policy engine's own consent
   flow). The `mt5-trading` skill walks the agent through preview -> approval ->
   execute.

If the spawned Python doesn't have `mt5_mcp` installed, point the registration
(your `.mcp.json` or the `claude mcp add` command) at the right interpreter
(e.g. `.venv\Scripts\python.exe`) - same shape as the snippet above.
