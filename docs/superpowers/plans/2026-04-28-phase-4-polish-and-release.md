# Phase 4 — Polish and v1.0 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `mt5-mcp` `1.0.0` to PyPI under a personal/neutral identity (`vincentwongso/mt5-mcp`), with the minimum docs and CI needed for a credible public release. No production code changes; the existing 243-test suite is untouched.

**Architecture:** Doc-and-config-only phase. Bump `pyproject.toml` to `1.0.0` and re-author it. Rewrite `README.md` for a first-time PyPI user (including a Windows-VPS deployment section). Add `SECURITY.md`, `CHANGELOG.md`, two example Claude Desktop configs (stdio + HTTP), one Cursor config, and a single GitHub Actions test workflow. Tag `v1.0.0`, swap the local `origin` URL, then hand off to the user for the final `git push` and `uv publish` steps.

**Tech Stack:** Python 3.10+ (project), `hatchling` (build), `uv` (sync/build/publish), GitHub Actions (CI), PyPI (distribution).

**Reference:** Spec at [`docs/superpowers/specs/2026-04-28-phase-4-polish-and-release-design.md`](../specs/2026-04-28-phase-4-polish-and-release-design.md) (commit `3ad4504`).

---

## Pre-flight

Before starting Task 1:

- [ ] **Verify the working tree is clean** (no uncommitted changes from earlier work).

Run: `git status`
Expected: `nothing to commit, working tree clean`

- [ ] **Confirm baseline test suite is green.**

Run: `uv run pytest -m "not integration"`
Expected: 243 passed, 0 failed.

- [ ] **Confirm we're on `main` with `phase-3-complete` shipped.**

Run: `git log --oneline -1`
Expected: shows `e5f2a10 docs(phase-3): document resources, HTTP transport, and streaming subsystem` or a later commit on `main` (the spec commit `3ad4504` is acceptable too).

If any of the above fail, stop and resolve before starting Task 1.

---

## Task 1: Update `pyproject.toml` metadata and version

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Open `pyproject.toml` and apply three edits.**

Replace line 7:

```toml
version = "0.1.0"
```

with:

```toml
version = "1.0.0"
```

Replace line 11:

```toml
authors = [{ name = "Fintrix Markets", email = "security@fintrixmarkets.com" }]
```

with:

```toml
authors = [{ name = "Vincent", email = "vincent.wongso.saputro@gmail.com" }]
```

After the `[project.scripts]` block (which currently ends at line 40), and BEFORE the `[tool.hatch.build.targets.wheel]` block, insert a new `[project.urls]` block:

```toml
[project.urls]
Repository = "https://github.com/vincentwongso/mt5-mcp"
Issues = "https://github.com/vincentwongso/mt5-mcp/issues"
Changelog = "https://github.com/vincentwongso/mt5-mcp/blob/main/CHANGELOG.md"
```

Leave everything else (`[build-system]`, `dependencies`, `optional-dependencies`, `classifiers`, hatch wheel config, pytest config) unchanged.

- [ ] **Step 2: Verify the edits parse.**

Run: `uv build`
Expected: produces `dist/mt5_mcp-1.0.0-py3-none-any.whl` and `dist/mt5_mcp-1.0.0.tar.gz`. No errors.

- [ ] **Step 3: Spot-check the wheel metadata.**

Run: `python -c "import zipfile; print(zipfile.ZipFile('dist/mt5_mcp-1.0.0-py3-none-any.whl').read('mt5_mcp-1.0.0.dist-info/METADATA').decode())"`

Expected: METADATA contains `Name: mt5-mcp`, `Version: 1.0.0`, `Author-email: Vincent <vincent.wongso.saputro@gmail.com>`, and three `Project-URL:` lines (Repository, Issues, Changelog).

- [ ] **Step 4: Clean up build artifacts before committing.**

Run: `rm -rf dist`

The `dist/` directory should not be committed; we'll regenerate it in Task 7.

- [ ] **Step 5: Commit.**

```bash
git add pyproject.toml
git commit -m "release(phase-4): bump version to 1.0.0, update author and URLs"
```

---

## Task 2: Create `SECURITY.md`

**Files:**
- Create: `SECURITY.md`

- [ ] **Step 1: Write the full file.**

Create `SECURITY.md` with this exact content:

```markdown
# Security Policy

## Reporting a vulnerability

Please report security issues by emailing **vincent.wongso.saputro@gmail.com** with the subject prefix `[mt5-mcp security]`. Include:

- A description of the issue and how to reproduce it.
- The version of `mt5-mcp` you're running (`pip show mt5-mcp`).
- Your operating system and Python version.

You should receive an acknowledgement within 7 days. Please do not file public GitHub issues for security reports until a fix is released.

## Supported versions

| Version | Supported |
|---------|-----------|
| `1.x`   | ✅ Yes    |
| `0.x`   | ❌ No (pre-release; please upgrade to `1.x`) |

Security fixes ship as patch releases on the latest minor of the `1.x` line.

## Scope

`mt5-mcp` is **not** the security boundary. The broker's MetaTrader 5 server enforces hard limits — margin requirements, max-lot sizes, symbol permissions, account-level protections. Pre-flight checks in the policy engine (`max_notional_per_trade`, `max_daily_loss`, etc.) are UX guardrails to catch agent mistakes early, not security controls. They protect a misbehaving agent from itself; they do not protect against an attacker with terminal access.

The MCP runs locally in the customer's process tree. It has no cloud component, no telemetry, and no auto-update. Threats outside this scope — for example, compromise of the broker's MT5 server, theft of MT5 login credentials, OS-level keylogging or screen capture, or compromise of the agent runtime — are out of scope for `mt5-mcp` itself.

## What we consider in scope

Bug reports against any of the following will get a fix release:

- **Idempotency-replay correctness** — a request with the same `idempotency_key` returning a different result than the first call.
- **Audit-log integrity** — a mutating action that completes without a corresponding entry in the audit JSONL, or a forged/missing field in an audit entry.
- **Consent-flow integrity** — a retry passing `approval_confirmed=true` succeeding when its fields don't match the original `ApprovalPreview` (within tolerance).
- **HTTP transport bearer-token check** — non-constant-time token comparison, or a path that bypasses the check.
- **Config-file loading** — a config that should be rejected (invalid type, missing required field) being silently accepted, or a path-traversal in any user-supplied path field.

## Out of scope

- Reports that require attacker-controlled access to the operator's machine (the local-first threat model assumes the operator is trusted).
- Reports against the upstream `MetaTrader5` Python library — file those with MetaQuotes.
- "Best practice" suggestions without a demonstrated bug (please open a regular issue or PR).
```

- [ ] **Step 2: Verify the file is well-formed Markdown.**

Run: `cat SECURITY.md | head -5`
Expected: starts with `# Security Policy` and the next non-empty line is `## Reporting a vulnerability`.

- [ ] **Step 3: Commit.**

```bash
git add SECURITY.md
git commit -m "docs(phase-4): add SECURITY.md with disclosure policy and scope"
```

---

## Task 3: Create `CHANGELOG.md`

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Gather commit ranges from git log to keep entries factual.**

Run: `git log --oneline --reverse v0.1..HEAD 2>/dev/null || git log --oneline --reverse | head -50`

If `v0.1` tag doesn't exist, that's fine — we have the phase-tag references in `CLAUDE.md` for the factual content. We don't need exact commit hashes in the changelog itself.

- [ ] **Step 2: Write the full file.**

Create `CHANGELOG.md` with this exact content:

```markdown
# Changelog

All notable changes to `mt5-mcp` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting at `1.0.0`.

## [1.0.0] - 2026-04-28

First public release on PyPI. The underlying feature set is the cumulative output of phases 1–3; this release adds packaging, public-facing documentation, and CI.

### Added

- Public PyPI distribution: `pip install mt5-mcp`.
- `SECURITY.md` with vulnerability disclosure policy and explicit scope statement (`mt5-mcp` is not the security boundary; the broker is).
- `CHANGELOG.md` (this file), retroactively documenting phases 1–3.
- `examples/clients/` directory with drop-in MCP-client configs:
  - `claude-desktop-stdio.json` — Claude Desktop stdio transport.
  - `claude-desktop-http.json` — Claude Desktop HTTP transport (for VPS / SSH-tunnel deployments).
  - `cursor.json` — Cursor stdio transport.
- README section on deploying `mt5-mcp` to a Windows VPS (Pattern A: agent on VPS; Pattern B: agent local with SSH tunnel to loopback HTTP).
- GitHub Actions test CI workflow (`pytest -m "not integration"` on Windows runners across Python 3.10 / 3.11 / 3.12, on push to `main` and on PRs).
- `[project.urls]` block in `pyproject.toml` (Repository, Issues, Changelog).

### Changed

- Bumped version `0.1.0` → `1.0.0`.
- README rewritten for first-time PyPI users; install instructions now lead with `pip install mt5-mcp`. Repo URL updated from `Fintrix-Markets/mt5-trading-mcp` to `vincentwongso/mt5-mcp`.
- `pyproject.toml` author updated from "Fintrix Markets" to "Vincent". Security contact moved to a personal email.

### Removed

- Internal phase-tracking references (`phase-2-complete`, "243 passing unit tests" status lines, etc.) removed from public-facing docs. They remain in `CLAUDE.md` for contributors.

## [0.3.0] - 2026-04-27

Resources, HTTP transport, and streaming subsystem (Phase 3, internal release).

### Added

- Three subscribable MCP resources: `account://current`, `positions://current`, `quotes://{symbol}`.
- Streaming subsystem (`src/mt5_mcp/streaming/`): a single shared `Poller` daemon thread + `Dispatcher` for per-URI change-fanout.
- HTTP transport (`serve --transport http`), loopback-only, with optional bearer-token auth (`transport.http.auth_token`).
- `[streaming]` config section with configurable poll cadences (`quote_poll_ms`, `account_poll_ms`).
- `doctor` gained a `[streaming]` check.
- `FastMCPSubscriber` adapter bridging the Poller's daemon thread to the FastMCP asyncio event loop.

### Changed

- Change-detection for `account://current` and `positions://current` excludes floating P&L by design — only identity/structural changes wake subscribers.

## [0.2.0] - 2026-04-26

Mutating tools and policy engine (Phase 2, internal release).

### Added

- Four mutating MCP tools: `place_order`, `modify_order`, `cancel_order`, `close_position`.
- Policy engine (`src/mt5_mcp/policy/`) composing four submodules: `preflight`, `consent`, `idempotency`, `audit`.
- SQLite-backed idempotency replay (per-OS path via `platformdirs`).
- Append-only JSONL audit log with size-based rotation.
- `doctor --smoke-trade` flag for live-terminal verification of the place-then-close round-trip.

### Changed

- Approval flow simplified to a single `approval_confirmed` boolean + `approval_request_id`; the earlier HMAC-signed token design was dropped.
- "Soft limits" renamed "Pre-flight limits" with explicit non-security framing (architecture §8).

## [0.1.0] - 2026-04-24

Skeleton and read tools (Phase 1, internal release).

### Added

- Nine read MCP tools: `ping`, `get_terminal_info`, `get_account_info`, `get_quote`, `get_symbols`, `get_market_hours`, `get_positions`, `get_orders`, `get_history`.
- Two CLI commands: `doctor`, `export-symbols`.
- `MetaTrader5`-wrapping adapter with a singleton client, symbol prep, and type conversions.
- Config loader with `watchdog`-based hot-reload.
- FastMCP server bootstrap.
- 89 unit tests against a hand-rolled `FakeMT5` (no live terminal needed).
```

- [ ] **Step 3: Verify the file.**

Run: `head -10 CHANGELOG.md`
Expected: starts with `# Changelog` and the most recent entry is `## [1.0.0] - 2026-04-28`.

- [ ] **Step 4: Commit.**

```bash
git add CHANGELOG.md
git commit -m "docs(phase-4): add CHANGELOG.md retroactively covering 0.1 → 1.0"
```

---

## Task 4: Create example client configs

**Files:**
- Create: `examples/clients/claude-desktop-stdio.json`
- Create: `examples/clients/claude-desktop-http.json`
- Create: `examples/clients/cursor.json`

- [ ] **Step 1: Create the `examples/clients/` directory.**

Run: `mkdir -p examples/clients`

- [ ] **Step 2: Write `examples/clients/claude-desktop-stdio.json`.**

Create the file with this exact content:

```json
{
  "mcpServers": {
    "mt5-mcp": {
      "command": "python",
      "args": ["-m", "mt5_mcp", "serve"]
    }
  }
}
```

This is a drop-in `mcpServers` object. Users paste the inner `"mt5-mcp": { ... }` entry into their existing `claude_desktop_config.json` (typically at `%APPDATA%\Claude\claude_desktop_config.json` on Windows).

If `python` is not on PATH, the README explains substituting an absolute path to a venv's Python (e.g., `C:\\Users\\<name>\\.venvs\\mt5-mcp\\Scripts\\python.exe`).

- [ ] **Step 3: Write `examples/clients/claude-desktop-http.json`.**

Create the file with this exact content:

```json
{
  "mcpServers": {
    "mt5-mcp": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

This variant assumes the user has `mt5-mcp serve --transport http` already running (locally, or forwarded via SSH from a VPS — see the README VPS section). Port `8765` matches the default in `[transport.http] port`.

- [ ] **Step 4: Write `examples/clients/cursor.json`.**

Create the file with this exact content:

```json
{
  "mcpServers": {
    "mt5-mcp": {
      "command": "python",
      "args": ["-m", "mt5_mcp", "serve"]
    }
  }
}
```

Cursor's `~/.cursor/mcp.json` accepts the same `mcpServers` schema as Claude Desktop. Stdio only — Cursor's HTTP MCP support is a corner case.

- [ ] **Step 5: Verify all three files are valid JSON.**

Run: `python -c "import json; [json.load(open(f)) for f in ['examples/clients/claude-desktop-stdio.json', 'examples/clients/claude-desktop-http.json', 'examples/clients/cursor.json']]; print('all valid')"`
Expected: `all valid` printed, no exceptions.

- [ ] **Step 6: Commit.**

```bash
git add examples/clients/claude-desktop-stdio.json examples/clients/claude-desktop-http.json examples/clients/cursor.json
git commit -m "docs(phase-4): add example MCP client configs (Claude Desktop stdio/HTTP, Cursor)"
```

---

## Task 5: Add GitHub Actions test workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Create the `.github/workflows/` directory.**

Run: `mkdir -p .github/workflows`

- [ ] **Step 2: Write `.github/workflows/test.yml`.**

Create the file with this exact content:

```yaml
name: tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: windows-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv with Python ${{ matrix.python-version }}
        uses: astral-sh/setup-uv@v3
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Run unit tests
        run: uv run pytest -m "not integration" -v
```

Key choices:

- **Windows runner only.** The `MetaTrader5` PyPI package is gated by `platform_system == 'Windows'` in `pyproject.toml`, so it would simply not install on Linux runners — but the rest of the codebase imports `MetaTrader5` lazily and the tests use `FakeMT5`. We pick Windows-only to match production reality and avoid divergent CI/local behavior.
- **`fail-fast: false`.** A failure on Python 3.10 shouldn't cancel 3.11/3.12 — we want the full matrix signal.
- **`-m "not integration"`.** The integration test (`tests/test_http_integration.py`) starts an HTTP server and exercises the real transport; it's marked `integration` and excluded from CI. CI runs the 242 unit tests; the integration test is left for local / pre-tag verification.
- **`astral-sh/setup-uv@v3`.** Idiomatic for `uv`-based projects; handles uv installation and Python version selection in one action.

- [ ] **Step 3: Verify the YAML parses.**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('valid yaml')"`
Expected: `valid yaml` printed, no exceptions.

If `yaml` isn't installed in the project venv: `python -c "import json; print('skipping yaml check; will be validated when CI runs')"` and rely on the post-push CI run as the verification.

- [ ] **Step 4: Commit.**

```bash
git add .github/workflows/test.yml
git commit -m "ci(phase-4): add Windows-runner test workflow for Python 3.10/3.11/3.12"
```

---

## Task 6: Rewrite `README.md`

**Files:**
- Modify: `README.md` (full rewrite)

This task wholesale replaces `README.md`. The new content is below — copy it verbatim. Do not edit incrementally; this is cleaner as a full rewrite.

- [ ] **Step 1: Replace the entire contents of `README.md` with the following.**

```markdown
# mt5-mcp

Model Context Protocol server wrapping the MetaTrader 5 Python library — exposes a logged-in MT5 terminal as a set of MCP tools an AI agent can call.

**Status:** v1.0 — first public release. Windows + Python 3.10+ required.

## Requirements

- Windows (the `MetaTrader5` Python library is Windows-only).
- Python 3.10 or newer.
- A running MetaTrader 5 terminal already logged into a broker.

## Install

From PyPI:

```bash
pip install mt5-mcp
```

Or with [`uv`](https://docs.astral.sh/uv/):

```bash
uv pip install mt5-mcp
```

### From source (for contributors)

```bash
git clone https://github.com/vincentwongso/mt5-mcp.git
cd mt5-mcp
uv sync --extra dev
```

## Quick start

```bash
# 1. Verify the MT5 terminal is reachable.
python -m mt5_mcp doctor

# 2. (Optional) Dump every tradeable symbol so you have a reference handy.
python -m mt5_mcp export-symbols --output symbols.csv

# 3. Run the server on stdio (default — what an MCP client invokes as a subprocess).
python -m mt5_mcp serve
```

To register the server with an MCP client, see the [example configs](https://github.com/vincentwongso/mt5-mcp/tree/main/examples/clients) — drop-in JSON snippets for Claude Desktop and Cursor.

## What it does

### Read-only tools (no consent gate)

| Tool | Purpose |
|---|---|
| `ping` | Health check; verifies the terminal is reachable. |
| `get_terminal_info` | Connection state, broker TZ offset, MT5 build. |
| `get_account_info` | Balance, equity, margin, leverage, currency. |
| `get_quote(symbol)` | Current bid/ask. |
| `get_symbols(category?)` | Tradeable instruments, optionally filtered. |
| `get_market_hours(symbol)` | Whether the symbol's session is open. |
| `get_positions(symbol?)` | Open positions. |
| `get_orders(symbol?)` | Pending orders. |
| `get_history(from_ts, to_ts, symbol?)` | Closed deals in a UTC range. |

### Mutating tools (preflight + consent + idempotency + audit)

| Tool | Purpose | Gate |
|---|---|---|
| `place_order` | Market or pending order with optional SL/TP/deviation. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `modify_order` | Change SL/TP/expiry on a position or pending order. | Widening or removing SL/TP on a position → `ApprovalPreview`. Tightening auto-approves. |
| `close_position` | Close a position by ticket, in full or part. | Notional ≥ `auto_approve_notional` → `ApprovalPreview`. |
| `cancel_order` | Cancel a pending order by ticket. | Never gates (reduces exposure). |

When a tool returns an `ApprovalPreview`, the agent shows it to the human, then retries the same call with `approval_confirmed=true` and the original `approval_request_id`. The MCP validates the retry matches the preview (price drift ≤ `max(0.5%, deviation × point)`, identical symbol/side/type/volume/ticket). On mismatch the retry is refused as `INVALID_APPROVAL`.

All mutating tools accept an optional `idempotency_key`; pass a UUIDv4 to dedupe retries within `idempotency.ttl_seconds`.

### Resources (subscribable)

| URI | What it returns |
|---|---|
| `account://current` | Live account snapshot (balance, equity, margin, leverage, …). |
| `positions://current` | All open positions. |
| `quotes://{symbol}` | Current bid/ask for `symbol` (e.g. `quotes://EURUSD`). |

A subscribed client receives a `notifications/resources/updated` message when the underlying data changes, then re-reads the resource to get the latest snapshot. Floating P&L is excluded from the change-detection diff for `account://` and `positions://` (subscribers are only woken on balance-sheet or position-count changes); `quotes://{symbol}` notifies on any bid/ask change.

## MCP client setup

Drop-in config snippets are in [`examples/clients/`](https://github.com/vincentwongso/mt5-mcp/tree/main/examples/clients):

- **Claude Desktop, stdio:** `examples/clients/claude-desktop-stdio.json`. Paste the inner `mcpServers` entry into `%APPDATA%\Claude\claude_desktop_config.json`.
- **Claude Desktop, HTTP:** `examples/clients/claude-desktop-http.json`. For when `mt5-mcp serve --transport http` is already running.
- **Cursor:** `examples/clients/cursor.json`. Paste into `~/.cursor/mcp.json`.

If `python` isn't on PATH (or you want to pin a specific venv), substitute the absolute path:

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

## Configuration

Optional. Default config path:

- Windows: `%APPDATA%\mt5-mcp\config.toml`
- Linux/WSL: `$XDG_CONFIG_HOME/mt5-mcp/config.toml` (falls back to `~/.config/mt5-mcp/config.toml`)

The server starts with built-in defaults if the file is absent. Full schema documented in the [architecture spec, §7](https://github.com/vincentwongso/mt5-mcp/blob/main/mt5-mcp-architecture.md).

Minimal example:

```toml
[mt5]
terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

[policy]
auto_approve_notional = "1000.00"      # above this, place_order returns an ApprovalPreview
max_notional_per_trade = "10000.00"    # hard cap; no approval can override
max_realised_loss_per_close = "500.00" # close_position refuses if it would realise more
max_daily_loss = "2000.00"             # place_order refuses once daily realised loss hits this

[symbols]
allowlist = []  # if non-empty, only these symbols can be traded
denylist = []   # symbols here are always refused

[idempotency]
ttl_seconds = 86400  # 24h replay window for mutating tools that pass an idempotency_key

[transport.http]
# Only relevant when using --transport http. Loopback-only in v1.0.
port = 8765
auth_token = ""  # optional bearer token; leave empty to disable auth

[streaming]
quote_poll_ms = 200      # how often quotes://{symbol} checks for price changes
account_poll_ms = 1000   # how often account:// and positions:// are checked
```

The config file is hot-reloaded via `watchdog` whenever it changes on disk; broken edits are logged and ignored (the last-good config is retained).

**Storage paths** (idempotency DB and audit JSONL log) default to `platformdirs.user_data_dir("mt5-mcp", appauthor=False)`:

- Windows: `%LOCALAPPDATA%\mt5-mcp\{idempotency.db, audit.jsonl}`
- macOS: `~/Library/Application Support/mt5-mcp/{idempotency.db, audit.jsonl}`
- Linux: `~/.local/share/mt5-mcp/{idempotency.db, audit.jsonl}`

Both are overridable in `config.toml` under `[idempotency] path` and `[audit] path`.

## Transports

### stdio (default)

`python -m mt5_mcp` and `python -m mt5_mcp serve` both run in stdio mode. This is the correct choice for Claude Desktop, Cursor, and any agent runtime that manages the server as a subprocess.

### HTTP (opt-in)

For agent runtimes that prefer a long-running HTTP server instead of a subprocess:

```bash
python -m mt5_mcp serve --transport http
```

Constraints in v1.0:

- **Loopback-only** (`127.0.0.1`, `::1`, `localhost`). Binding to any other address raises a startup error. Direct LAN/internet exposure is intentionally not supported in v1.0; see the VPS deployment section below for the secure alternative.
- **Optional bearer-token authentication** via `transport.http.auth_token` in `config.toml`. When set, every request must carry `Authorization: Bearer <token>`. Comparison is constant-time.
- Uses the `streamable-http` FastMCP transport under the hood, which supports both request/response and SSE streaming on a single endpoint.

Default port: `8765` (configurable via `[transport.http] port`).

## Deploying to a Windows VPS

Common case: you want your MT5 terminal running 24/7 on a server, but laptops sleep. Two supported patterns:

### Pattern A — Agent + MCP both on the VPS

Simplest setup. RDP into the VPS, install Python and the MetaTrader 5 terminal, then:

```powershell
pip install mt5-mcp
python -m mt5_mcp doctor   # verify the terminal is reachable
```

Run your MCP client (Claude Desktop, Cursor, or another) on the VPS itself and register `mt5-mcp` via the stdio config snippet. The agent's context lives on the VPS.

Practical notes:

- Keep the MT5 terminal logged in across reboots — Windows Task Scheduler "At log on" is the simplest path. (Auto-login at the OS level is a separate concern; consult your VPS provider's docs.)
- The `config.toml` watchdog hot-reload still works — just edit the file on the VPS.

### Pattern B — Agent local, MCP on the VPS via SSH tunnel

Use this when you want your agent running on your laptop but the MT5 terminal on the VPS.

On the VPS, run the HTTP transport (loopback-bound):

```powershell
python -m mt5_mcp serve --transport http
```

On your local machine, open an SSH tunnel that forwards the loopback port:

```bash
ssh -L 8765:localhost:8765 user@vps-host
```

Now `http://localhost:8765/mcp` on your laptop reaches the MCP on the VPS — without ever exposing the HTTP port to the public internet. Use the [`claude-desktop-http.json`](https://github.com/vincentwongso/mt5-mcp/tree/main/examples/clients/claude-desktop-http.json) example to register it with Claude Desktop.

This is the secure default for remote MT5 terminals. Direct non-loopback HTTP binding is intentionally **not** supported in v1.0 — it would require a TLS termination story and tighter auth than a single bearer token. If you need it for a real deployment, please open an issue describing the use case.

### Keeping `mt5-mcp serve` running

For Pattern A's HTTP transport or Pattern B's VPS-side server, you'll want the process to survive reboots:

- **NSSM** ([Non-Sucking Service Manager](https://nssm.cc/)) is the lightest option — wrap `python -m mt5_mcp serve --transport http` as a Windows Service.
- A scheduled task with "At system startup" + a restart-on-failure policy works too.

`mt5-mcp` doesn't bundle a service wrapper; pick the one your ops setup already uses.

## Safety

`mt5-mcp` is not the security boundary — the broker's MT5 server enforces hard limits (margin, max-lot, symbol permissions). Pre-flight checks in the policy engine are UX guardrails to catch agent mistakes early, not security controls.

Mutating actions above the configured `auto_approve_notional` (or that widen stops) require explicit human approval via the `ApprovalPreview` flow. Every mutating call is recorded in an append-only audit JSONL log.

For vulnerability disclosure, see [`SECURITY.md`](https://github.com/vincentwongso/mt5-mcp/blob/main/SECURITY.md).

## Development

Clone and sync:

```bash
git clone https://github.com/vincentwongso/mt5-mcp.git
cd mt5-mcp
uv sync --extra dev
```

Run the test suite (no live terminal required — uses `FakeMT5`):

```bash
uv run pytest -v
```

Run unit tests only (skip the integration test that starts a real HTTP server):

```bash
uv run pytest -m "not integration" -v
```

Live-terminal smoke checks (require a running MT5 terminal logged into a broker; the smoke-trade variant places a real micro-lot order — use a demo account):

```bash
python -m mt5_mcp doctor
python -m mt5_mcp doctor --smoke-trade
```

CI runs the unit-test suite on Windows runners across Python 3.10 / 3.11 / 3.12 on every push to `main` and every PR.

## Architecture

The full design is in [`mt5-mcp-architecture.md`](https://github.com/vincentwongso/mt5-mcp/blob/main/mt5-mcp-architecture.md). Phase implementation plans live under [`docs/superpowers/plans/`](https://github.com/vincentwongso/mt5-mcp/tree/main/docs/superpowers/plans).

## Licence

MIT — see [`LICENCE`](https://github.com/vincentwongso/mt5-mcp/blob/main/LICENCE).
```

- [ ] **Step 2: Verify the file is well-formed.**

Run: `head -5 README.md`
Expected:

```
# mt5-mcp

Model Context Protocol server wrapping the MetaTrader 5 Python library — exposes a logged-in MT5 terminal as a set of MCP tools an AI agent can call.

**Status:** v1.0 — first public release. Windows + Python 3.10+ required.
```

- [ ] **Step 3: Verify no `Fintrix` references remain.**

Run: `grep -i fintrix README.md || echo "no fintrix references — good"`
Expected: `no fintrix references — good`.

- [ ] **Step 4: Verify all internal repo links use absolute GitHub URLs (PyPI rendering doesn't follow relative links).**

Run: `grep -E "\]\((\.\.?/|/[^/])" README.md || echo "no relative links — good"`
Expected: `no relative links — good`. (Markdown links like `[text](./file.md)` or `[text](/file.md)` would match this pattern; absolute `https://...` links won't.)

- [ ] **Step 5: Commit.**

```bash
git add README.md
git commit -m "docs(phase-4): rewrite README for v1.0 public release"
```

---

## Task 7: Local verification

This task makes no file changes. It runs the full set of pre-tag verification commands the spec §5 lists.

- [ ] **Step 1: Run the full unit-test suite.**

Run: `uv run pytest -m "not integration" -v`
Expected: 243 passed, 0 failed. (Test count is the cumulative Phase 1+2+3 total; this phase adds no new tests.)

- [ ] **Step 2: Run the integration test once locally.**

Run: `uv run pytest -m integration -v`
Expected: 1 passed (the HTTP integration test). If it fails, investigate before tagging.

- [ ] **Step 3: Build distribution artifacts.**

Run: `rm -rf dist && uv build`
Expected: produces `dist/mt5_mcp-1.0.0-py3-none-any.whl` and `dist/mt5_mcp-1.0.0.tar.gz`.

- [ ] **Step 4: Spot-check wheel METADATA contains the right version, author, and URLs.**

Run:

```bash
python -c "
import zipfile
m = zipfile.ZipFile('dist/mt5_mcp-1.0.0-py3-none-any.whl').read('mt5_mcp-1.0.0.dist-info/METADATA').decode()
for line in m.splitlines():
    if line.startswith(('Name:', 'Version:', 'Author-email:', 'Project-URL:', 'Summary:')):
        print(line)
"
```

Expected output (in some order):

```
Name: mt5-mcp
Version: 1.0.0
Summary: Model Context Protocol server wrapping the MetaTrader 5 Python library.
Author-email: Vincent <vincent.wongso.saputro@gmail.com>
Project-URL: Repository, https://github.com/vincentwongso/mt5-mcp
Project-URL: Issues, https://github.com/vincentwongso/mt5-mcp/issues
Project-URL: Changelog, https://github.com/vincentwongso/mt5-mcp/blob/main/CHANGELOG.md
```

- [ ] **Step 5: Install the wheel into a fresh Windows venv and run `doctor`.**

Run:

```bash
python -m venv "$TEMP/mt5-mcp-smoke"
"$TEMP/mt5-mcp-smoke/Scripts/pip" install dist/mt5_mcp-1.0.0-py3-none-any.whl
"$TEMP/mt5-mcp-smoke/Scripts/python" -m mt5_mcp doctor
```

Expected with a live MT5 terminal: 9× `[PASS]` (the `[streaming]` check is the 9th).
Expected without a live terminal: a `[FAIL]` line for the connection check, followed by clean error messages — no Python tracebacks. The smoke check is verifying the package installs and runs; not that the operator's MT5 is configured.

- [ ] **Step 6: Clean up smoke venv.**

Run: `rm -rf "$TEMP/mt5-mcp-smoke" dist`

- [ ] **Step 7: No commit needed for this task** — it's verification-only.

---

## Task 8: Update `CLAUDE.md` to reflect Phase 4 completion

**Files:**
- Modify: `CLAUDE.md`

This is the contributor-facing handover doc. It should reflect Phase 4 shipping and Phase 5 being queued.

- [ ] **Step 1: Update the status header.**

Find the line at the top of `CLAUDE.md`:

```markdown
**Status (last updated April 2026):** Phase 3 complete. Tag `phase-2-complete` marks the previous milestone. Phase 3 added 3 MCP resources (`account://current`, `positions://current`, `quotes://{symbol}`), a shared streaming subsystem (Poller + Dispatcher), and HTTP transport (`serve --transport http`, loopback-only). 243 passing unit tests. Phase 4 picks up polish + PyPI release.
```

Replace with:

```markdown
**Status (last updated April 2026):** Phase 4 complete — `mt5-mcp` v1.0.0 shipped to PyPI. Tag `phase-3-complete` marks the previous milestone. Phase 4 added the public README, `SECURITY.md`, `CHANGELOG.md`, example MCP client configs (Claude Desktop stdio + HTTP, Cursor), GitHub Actions test CI, and the `1.0.0` PyPI release. 243 passing unit tests (unchanged from Phase 3). Phase 5 (automated integration tests against a real MT5 demo) is queued.
```

- [ ] **Step 2: Update the "Where to start" section.**

Find the section starting at:

```markdown
## Where to start

1. **Architecture spec:** `mt5-mcp-architecture.md` (single source of truth for design).
2. **Phase 1 plan:** `docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md` (TDD-style, every step has the actual code).
3. **What's left:** Phase 4 (polish + PyPI release). See architecture §15.
```

Replace with:

```markdown
## Where to start

1. **Architecture spec:** `mt5-mcp-architecture.md` (single source of truth for design).
2. **Phase 1 plan:** `docs/superpowers/plans/2026-04-24-phase-1-skeleton-and-read-tools.md` (TDD-style, every step has the actual code).
3. **What's next:** Phase 5 (automated integration tests against a real MT5 demo). Spec to be written; user has demo account access. Architecture §15 currently ends at Phase 4 — Phase 5 will require an architecture-doc update.
```

- [ ] **Step 3: Add a "What Phase 4 added" section.**

Find the section:

```markdown
## What Phase 3 added

Three MCP resources (`account://current`, `positions://current`, `quotes://{symbol}`), all readable and subscribable. A shared streaming subsystem (`src/mt5_mcp/streaming/`) with a `Poller` daemon thread and a `Dispatcher` for per-URI change-fanout. Change-detection excludes floating P&L by design (see architecture §17). HTTP transport (`serve --transport http`), loopback-only, with optional bearer-token auth (`transport.http.auth_token`). A `FastMCPSubscriber` adapter bridges the Poller daemon thread to the FastMCP asyncio event loop via `asyncio.run_coroutine_threadsafe`. `doctor` gained a `[streaming]` check. Test helper `tests/_resource_helpers.py::read_resource(server, uri)` is the canonical way to drive resource handlers from tests. ~62 new unit tests (243 total). Architecture doc §17 and §18 added.
```

Immediately after that paragraph (before the next `## ...` heading), insert a new section:

```markdown
## What Phase 4 added

No production code changes — this was a packaging and docs phase. Bumped `pyproject.toml` to `1.0.0`, re-authored to "Vincent" with a personal security contact, added `[project.urls]`. Rewrote `README.md` for first-time PyPI users (with a Windows VPS deployment section covering both agent-on-VPS stdio and agent-local-via-SSH-tunnel HTTP patterns). Added `SECURITY.md`, `CHANGELOG.md`, three example client configs (`examples/clients/`), and a single GitHub Actions test workflow on Windows runners across Python 3.10/3.11/3.12. Tagged `v1.0.0` and published to PyPI. Repo moved from `Fintrix-Markets/mt5-trading-mcp` to `vincentwongso/mt5-mcp`.
```

- [ ] **Step 4: Add a "Phase 4 carryover" section.**

Find the section:

```markdown
## Phase 3 carryover (deferred to Phase 4)
```

Immediately after the bulleted list under that section, insert:

```markdown
## Phase 4 carryover (deferred to Phase 5+ or to ad-hoc fixes)

All items below were explicitly out of scope for v1.0; revisit as customer reports come in or as part of Phase 5 if integration tests surface them:

- **Auto-generated docs site** (was on the original Phase 4 list; deferred to v1.1+).
- **Plugin loader for third-party tools** (`src/mt5_mcp/plugins/` stub stays unwired; deferred to v1.1+).
- **Trusted Publishing GitHub Actions workflow** — manual `uv publish` worked for `1.0.0`; wire OIDC publishing if releases get frequent.
- **All Phase 2/3 carryovers** still deferred (idempotency TTL sweeper, audit prune CLI, `pick_filling_mode` improvements, non-loopback HTTP bind, per-subscriber backpressure, dead-subscriber TTL sweeper, test migration off `_tool_manager.get_tool().fn`).
- **`LICENCE` → `LICENSE` rename** — non-blocking; can roll into a future doc-only commit.
- **`CONTRIBUTING.md`** — non-blocking; add when the first external contribution lands.
```

- [ ] **Step 5: Verify the edits applied cleanly.**

Run: `head -5 CLAUDE.md`
Expected: the new status line is visible.

Run: `grep -c "## What Phase 4 added" CLAUDE.md`
Expected: `1`.

- [ ] **Step 6: Commit.**

```bash
git add CLAUDE.md
git commit -m "docs(phase-4): update CLAUDE.md for v1.0 ship and Phase 5 queue"
```

---

## Task 9: Tag `v1.0.0` and update local remote URL

**Files:** None (git operations).

- [ ] **Step 1: Confirm we're at the head of `main` with a clean tree.**

Run: `git status && git log --oneline -1`
Expected: working tree clean; the most recent commit is the CLAUDE.md update from Task 8.

- [ ] **Step 2: Create an annotated `v1.0.0` tag.**

Run:

```bash
git tag -a v1.0.0 -m "$(cat <<'EOF'
v1.0.0 — first public release

Cumulative Phase 1–3 feature set (read tools, mutating tools + policy
engine, resources + HTTP transport + streaming) plus Phase 4 packaging:
PyPI publish, public-facing README with Windows VPS deployment guide,
SECURITY.md, CHANGELOG, example client configs, and Windows-runner
test CI.

243 unit tests + 1 integration test passing on main.
EOF
)"
```

- [ ] **Step 3: Verify the tag.**

Run: `git tag -n5 v1.0.0`
Expected: shows `v1.0.0` followed by the multi-line annotation above.

- [ ] **Step 4: Update local `origin` URL to point at the new repo.**

The user's existing `origin` still points at `Fintrix-Markets/mt5-trading-mcp`. Swap it:

Run: `git remote set-url origin git@github.com:vincentwongso/mt5-mcp.git`

If the user prefers HTTPS over SSH, use `https://github.com/vincentwongso/mt5-mcp.git` instead.

- [ ] **Step 5: Verify the remote URL changed.**

Run: `git remote -v`
Expected:

```
origin	git@github.com:vincentwongso/mt5-mcp.git (fetch)
origin	git@github.com:vincentwongso/mt5-mcp.git (push)
```

- [ ] **Step 6: Do NOT push yet.** The push happens in Task 10 after the user creates the new GitHub repo.

---

## Task 10: User actions — create GitHub repo, push, publish to PyPI

**Files:** None (this task is run by the user, not the implementer agent).

This is the manual gate. The implementer agent stops here and posts the instructions below to the user. The user runs the commands in their own terminal so credentials never touch the agent's session.

- [ ] **Step 1: User creates the empty public repo on GitHub.**

The user goes to https://github.com/new and creates:

- **Owner:** `vincentwongso`
- **Repository name:** `mt5-mcp`
- **Visibility:** Public
- **Initialise:** leave all checkboxes unchecked (no README, no `.gitignore`, no LICENSE — we already have these locally).

The user confirms the empty repo URL is `https://github.com/vincentwongso/mt5-mcp`.

- [ ] **Step 2: User verifies `mt5-mcp` is available on PyPI.**

Open: https://pypi.org/project/mt5-mcp/

- If the page is `404 Not Found`: the name is available. Proceed.
- If the page exists with someone else's package: rename the package in `pyproject.toml` (line 6: `name = "mt5-mcp"` → `name = "mt5-trading-mcp"` or another fallback from spec §6 item 2), update README install instructions, re-run Task 7 to rebuild the wheel with the new name, and amend the changelog.

- [ ] **Step 3: User pushes `main` to the new repo (tag held back for now).**

```bash
git push -u origin main
```

This populates the new (empty) remote and triggers the `tests` workflow on the first commit. The `v1.0.0` tag is pushed in step 5 only after CI is green — that way the published tag never points at a known-broken commit.

- [ ] **Step 4: User waits for CI to pass.**

Open: https://github.com/vincentwongso/mt5-mcp/actions

Watch the `tests` workflow for the just-pushed commit. All three matrix jobs (Python 3.10/3.11/3.12 on `windows-latest`) should pass within ~10 minutes. **If any job fails:** stop here, post the failure log to the agent, and resolve before continuing. Common first-push failures: typo in `test.yml`, `uv sync` choking on a missing dependency, an environment-specific test that passes locally but not in CI. Fix forward — make the patch on `main`, push again, wait for the next CI run.

- [ ] **Step 5: After CI is green, user pushes the tag.**

```bash
git push origin v1.0.0
```

This is a no-op for CI (the workflow only triggers on push to `main`, not on tag push) and just publishes the tag.

- [ ] **Step 6: User configures PyPI credentials (one-time setup).**

If this is the user's first PyPI publish:

1. Create an account at https://pypi.org/account/register/.
2. Verify the email.
3. Generate an API token at https://pypi.org/manage/account/token/. Scope it to "Entire account" for the first publish; we can scope it to just `mt5-mcp` after the project page exists.
4. Set `UV_PUBLISH_TOKEN` in the shell or write `~/.pypirc` per `uv` docs.

- [ ] **Step 7: User builds the distribution artifacts.**

```bash
rm -rf dist
uv build
```

Expected: produces `dist/mt5_mcp-1.0.0-py3-none-any.whl` and `dist/mt5_mcp-1.0.0.tar.gz`.

- [ ] **Step 8: User publishes to PyPI.**

```bash
uv publish
```

Expected: `uv publish` uploads both artifacts to PyPI. If `UV_PUBLISH_TOKEN` is not set, `uv` prompts for the token interactively.

- [ ] **Step 9: User confirms the PyPI listing.**

Open: https://pypi.org/project/mt5-mcp/1.0.0/

Verify:

- Version `1.0.0` is shown.
- Author is `Vincent`.
- The README renders correctly (no broken links, tables look right).
- The three project URLs (Repository, Issues, Changelog) are listed on the sidebar.

- [ ] **Step 10: User pings the agent** so Task 11 (post-publish verification) can run.

---

## Task 11: Post-publish verification

**Files:** None (verification-only).

After the user confirms Task 10 step 9 succeeded (PyPI listing looks right), the agent (or user) closes the loop with an end-to-end install from PyPI.

- [ ] **Step 1: Install from PyPI into a fresh venv.**

Run:

```bash
python -m venv "$TEMP/mt5-mcp-pypi"
"$TEMP/mt5-mcp-pypi/Scripts/pip" install mt5-mcp
"$TEMP/mt5-mcp-pypi/Scripts/python" -c "import mt5_mcp; print(mt5_mcp.__name__)"
```

Expected: `pip` resolves `mt5-mcp==1.0.0`; the import line prints `mt5_mcp`.

- [ ] **Step 2: Run `doctor` from the PyPI-installed package.**

Run: `"$TEMP/mt5-mcp-pypi/Scripts/python" -m mt5_mcp doctor`
Expected: same as Task 7 step 5 (9× `[PASS]` with a live terminal; clean error messages without one).

- [ ] **Step 3: Paste the Claude Desktop stdio snippet into a real config and confirm registration.**

The user does this manually:

1. Open `%APPDATA%\Claude\claude_desktop_config.json`.
2. Paste the contents of `examples/clients/claude-desktop-stdio.json` (or merge the inner `mt5-mcp` entry into an existing `mcpServers` block).
3. Restart Claude Desktop.
4. Confirm `mt5-mcp` appears in the available tools list.

If it doesn't appear: check Claude Desktop's MCP log file (`%APPDATA%\Claude\logs\mcp-server-mt5-mcp.log`) for the failure mode — usually a missing `python` on PATH (fix by substituting the absolute venv path per the README "MCP client setup" section).

- [ ] **Step 4: Clean up smoke venv.**

Run: `rm -rf "$TEMP/mt5-mcp-pypi"`

- [ ] **Step 5: No commit needed.** Phase 4 is shipped.

---

## Done

When Tasks 1–11 are complete:

- `mt5-mcp 1.0.0` is on PyPI, installable via `pip install mt5-mcp`.
- `github.com/vincentwongso/mt5-mcp` is public, with green CI.
- Local `main` is at the CLAUDE.md-update commit; the `v1.0.0` tag points at the same commit.
- `CLAUDE.md` reflects v1.0 shipped and queues Phase 5.

Hand off to Phase 5 (integration tests against MT5 demo) when the user is ready.
