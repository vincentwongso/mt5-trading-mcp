# Phase 4 — Polish and v1.0 Release

**Status:** Design approved 2026-04-28. Awaits implementation plan (`writing-plans`).
**Owner:** Vincent
**Phase 3 commit:** `e5f2a10` (`phase-3-complete` tag)
**Architecture spec:** `mt5-mcp-architecture.md` §15 (phase order)

---

## 1. Goal

Ship `mt5-mcp` `1.0.0` to PyPI under a personal/neutral identity, with the minimum docs and CI needed for a credible public release. No production code changes. Defer auto-generated docs site, plugin loader, and all Phase 2/3 technical-debt carryovers to v1.1+.

Phase 4 closes when:

1. `pip install mt5-mcp` from a fresh venv installs `1.0.0` and `python -m mt5_mcp doctor` runs.
2. The repo is public at `github.com/vincentwongso/mt5-mcp` with green CI on the latest commit on `main`.
3. The PyPI project page renders the rewritten README, shows the right author and URLs, and resolves all links.
4. `SECURITY.md` and `CHANGELOG.md` exist and reflect the project's actual posture and history.
5. Phase 1+2+3 tests (243) still pass — no regressions.

This is a single-tag delivery: `v1.0.0`.

---

## 2. Foundation decisions (locked during brainstorm)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Tight MVP scope.** Ship release-blockers only: PyPI release, README rewrite, SECURITY.md, CHANGELOG, example client configs, basic CI. Skip docs site, plugin loader, all carryovers. | A docs site and a plugin loader both benefit from real-user feedback before they're built. Carryovers have no active complaint behind them. The smallest credible v1.0 is the right v1.0. |
| 2 | **Personal/neutral identity.** Repo at `github.com/vincentwongso/mt5-mcp`, author `Vincent`, security contact `vincent.wongso.saputro@gmail.com`. Drop all `Fintrix-Markets` / `fintrixmarkets.com` references. | Architecture is broker-agnostic by design (CLAUDE.md "Don't surprise the user"). A broker-named repo or contact undercuts that stance. Personal identity is honest and clean. |
| 3 | **Version `1.0.0`, not `0.4.0`.** | Architecture §15 explicitly calls Phase 4 "v1.0 release on PyPI." All planned features shipped, 243 tests green, contract is clear. Going to `1.0` commits to semver going forward — that's the right signal for an external release. |
| 4 | **Test CI only, no publish workflow.** Single GitHub Actions workflow runs `pytest -m "not integration"` on push and PR. PyPI publish for `1.0.0` is a manual `uv build && uv publish` step. | Manual publish for the first release proves the path. A trusted-publishing workflow can be added in v1.0.1 if releases get frequent. Don't pre-build infrastructure. |
| 5 | **SECURITY.md is short.** Disclosure email + supported versions + a one-paragraph "the broker is the security boundary, not the MCP" scope statement. No formal STRIDE threat model. | Architecture doc §12 ("Security & threat model") already documents threat surface. Duplicating it as a separate threat-model document is wasted motion for a one-engineer project. The short SECURITY.md is what users actually need to find the disclosure path. |
| 6 | **Two example client configs, not three.** Claude Desktop and Cursor only. Skip OpenClaw. | Claude Desktop and Cursor cover the dominant MCP-host audience. Adding OpenClaw is unfounded scope until someone asks for it. |
| 7 | **No production code changes.** No new modules, no new tests. The 243-test suite is unchanged. | This phase is exclusively packaging and docs. Mixing in code refactors invites scope drift and regression risk on the eve of a public release. |
| 8 | **User performs the GitHub repo-creation, remote-swap, and `uv publish` steps.** I prepare local commits and the release artifact; the actual push to a new remote and PyPI upload happen in the user's terminal so credentials never touch this session. | Standard separation: I edit files, the user runs commands that touch shared state with credentials. |
| 9 | **README documents Windows VPS deployment.** Two patterns: agent-on-VPS (stdio) and agent-local-via-SSH-tunnel (loopback HTTP). Direct non-loopback HTTP exposure stays deferred. | Common real-world use case — MT5 terminal needs to run 24/7, laptops sleep. SSH tunnel is the secure default and works with v1.0's loopback-only HTTP without requiring the deferred non-loopback feature. |

---

## 3. File layout

All paths relative to repo root. **No `src/` changes.**

```
pyproject.toml                          # MODIFIED: version 1.0.0, author, urls
README.md                               # REWRITTEN: PyPI install, new repo URL, drop Phase-N status
SECURITY.md                             # NEW: disclosure policy, scope statement
CHANGELOG.md                            # NEW: Keep a Changelog format, retroactive 0.1 → 1.0
examples/clients/claude-desktop-stdio.json  # NEW: claude_desktop_config.json snippet (stdio)
examples/clients/claude-desktop-http.json   # NEW: claude_desktop_config.json snippet (HTTP)
examples/clients/cursor.json                # NEW: Cursor MCP registration snippet
.github/workflows/test.yml              # NEW: pytest CI, Windows runner, Python 3.10/3.11/3.12
```

CLAUDE.md stays as-is during the design and plan phases. The implementation plan's final step updates CLAUDE.md's status header to "Phase 4 complete — v1.0.0 shipped" and the "Where to start" section.

---

## 4. File-by-file specification

### 4.1 `pyproject.toml`

Diff intent:

- `version = "0.1.0"` → `version = "1.0.0"`
- `authors = [{ name = "Fintrix Markets", email = "security@fintrixmarkets.com" }]` → `authors = [{ name = "Vincent", email = "vincent.wongso.saputro@gmail.com" }]`
- Add a `[project.urls]` block:
  - `Repository = "https://github.com/vincentwongso/mt5-mcp"`
  - `Issues = "https://github.com/vincentwongso/mt5-mcp/issues"`
  - `Changelog = "https://github.com/vincentwongso/mt5-mcp/blob/main/CHANGELOG.md"`

Everything else (build system, dependencies, optional-dependencies, classifiers, scripts, hatch config, pytest config) stays.

Acceptance: `uv build` produces `dist/mt5_mcp-1.0.0-py3-none-any.whl` and `mt5_mcp-1.0.0.tar.gz`; `python -m pip install dist/mt5_mcp-1.0.0-py3-none-any.whl` succeeds in a fresh venv on Windows.

### 4.2 `README.md` (rewrite)

Audience pivot: from "internal handover notes" to "first-time user installing from PyPI."

Required sections (in order):

1. **Title + one-line tagline** — same as today.
2. **Status line** — replace "Status: v0.3, Phase 3 complete..." with a one-liner like "Status: v1.0 — first public release. Windows + Python 3.10+ required."
3. **Requirements** — Windows, Python 3.10+, running MT5 terminal logged into a broker. Same as today.
4. **Install** — lead with `pip install mt5-mcp`. The "From source" subsection comes second and uses `git clone https://github.com/vincentwongso/mt5-mcp.git`.
5. **Quick start** — a 3-line minimal example: install, run `doctor`, register with an MCP client. Link to `examples/clients/`.
6. **What it does** — bullet list of the 13 tools (9 read + 4 mutating) and 3 resources, one line each. Pulled from architecture doc.
7. **Configuration** — point at the architecture doc's config section, plus a short `[transport.http]` snippet showing how to enable HTTP transport.
8. **Deploying to a Windows VPS** — covers the common "I want my MT5 terminal running 24/7 on a server" use case. Two patterns:
   - **Pattern A: Agent + MCP both on the VPS.** RDP in, install Python + MetaTrader5 terminal + `mt5-mcp`, run Claude Desktop (or other MCP host) on the VPS, register `mt5-mcp` via stdio. Simplest setup; agent context lives on the VPS.
   - **Pattern B: Agent local, MCP on VPS via SSH tunnel.** Run `mt5-mcp serve --transport http` on the VPS (loopback-bound, since v1.0 only allows loopback). On the local machine, open an SSH tunnel: `ssh -L 8765:localhost:8765 user@vps`. Local agent connects to `http://localhost:8765`. This is the secure default — the HTTP port never appears on the public internet.
   - Explicit non-goal in v1.0: binding the HTTP transport to a non-loopback address. Direct LAN/internet exposure of the HTTP server is deferred to v1.1+ pending real customer demand and a hardening pass.
   - Short list of practical VPS notes: keep MT5 terminal logged in across reboots (Windows Task Scheduler at logon), keep `mt5-mcp serve` running (NSSM or Windows Service wrapper — link out, don't bundle one), watchdog hot-reload still works (just edit `config.toml` on the VPS).
9. **Safety** — short paragraph: pre-flight checks are UX guardrails not security; the broker enforces hard limits; consent-required mutations require human approval. Link to SECURITY.md.
10. **Development** — `pytest` instructions, link to `CONTRIBUTING.md` (or "contributions welcome via PR" if no CONTRIBUTING.md yet).
11. **License** — MIT, link to `LICENCE`.

URL replacements (all instances): `Fintrix-Markets/mt5-trading-mcp` → `vincentwongso/mt5-mcp`; `git@github.com:` SSH remote → `https://github.com/` HTTPS for public-facing examples (SSH stays as a developer alternative).

Drop entirely: any "Phase N complete," "243 passing unit tests," `phase-2-complete` tag references — those are dev-internal and confuse first-time readers.

Acceptance: a developer who has never seen this project can `pip install mt5-mcp`, run `python -m mt5_mcp doctor`, and register the MCP with Claude Desktop using only the README and the `examples/clients/` snippets. A VPS-deploying user can follow §8 of the README to get either Pattern A or Pattern B working without consulting outside docs.

### 4.3 `SECURITY.md` (new)

Short, four-section format:

1. **Reporting a vulnerability** — email `vincent.wongso.saputro@gmail.com` with the prefix `[mt5-mcp security]`. Expect acknowledgement within 7 days.
2. **Supported versions** — `1.x` is supported; `0.x` is not.
3. **Scope** — explicit one-paragraph statement: "mt5-mcp is not the security boundary. The broker's MT5 server enforces hard limits (margin, max-lot, symbol permissions). Pre-flight checks in the policy engine are UX guardrails to catch agent mistakes early — not security controls. The MCP runs locally in the customer's process tree; it has no cloud component and no telemetry. Threats outside this scope (e.g., compromise of the broker's MT5 server, theft of MT5 login credentials, OS-level keylogging) are out of scope for `mt5-mcp` itself."
4. **What we consider in scope** — short bullet list: idempotency-replay correctness, audit-log integrity, consent-flow integrity, HTTP transport bearer-token check, config-file loading. Bug reports against any of these get a fix release.

Length target: ~40-60 lines. Not a STRIDE document.

Acceptance: SECURITY.md renders correctly on the GitHub repo's Security tab and the email address is exact.

### 4.4 `CHANGELOG.md` (new)

[Keep a Changelog](https://keepachangelog.com/) format. Retroactive entries by phase:

- `## [1.0.0] - 2026-04-28` — first PyPI release; lists Phase 4 changes (packaging, README, SECURITY.md, CI) and notes that the underlying feature set is the cumulative Phase 1+2+3 deliverable.
- `## [0.3.0] - 2026-04-27` — resources, HTTP transport, streaming subsystem (Phase 3).
- `## [0.2.0] - 2026-04-26` — mutating tools and policy engine (Phase 2).
- `## [0.1.0] - 2026-04-24` — skeleton and read tools (Phase 1).

Each entry uses Added / Changed / Deprecated / Removed / Fixed / Security headings as relevant. Pull facts from existing phase commit messages and CLAUDE.md status sections — don't invent history.

Acceptance: every line is verifiable against `git log --oneline` and the existing CLAUDE.md "What Phase N added" sections.

### 4.5 `examples/clients/claude-desktop.json` (new)

Snippet showing the `mt5-mcp` registration in the user's `claude_desktop_config.json`. JSON has no comments, so the file is pure JSON; the README's "Quick start" / VPS section provides the framing (where to paste — `%APPDATA%\Claude\claude_desktop_config.json` on Windows — and which keys are required vs optional). To keep both stdio and HTTP flavors discoverable without inventing a JSONC dialect, ship two files: `claude-desktop-stdio.json` and `claude-desktop-http.json`, each a complete drop-in `mcpServers` object.

- `claude-desktop-stdio.json`: the standard `command` + `args` pattern invoking `python -m mt5_mcp serve`. The default users start with.
- `claude-desktop-http.json`: the HTTP-transport variant for users who run `mt5-mcp serve --transport http`. Useful for the README VPS Pattern B (SSH tunnel) flow.

Acceptance: pasting the stdio snippet into a real Claude Desktop config (after rewriting paths to match the user's venv) successfully registers `mt5-mcp` and the tool list populates.

### 4.6 `examples/clients/cursor.json` (new)

Same pattern, adapted to Cursor's `~/.cursor/mcp.json` format. Stdio version only (HTTP is a corner case for Cursor).

Acceptance: pasting into a real Cursor config registers the MCP.

### 4.7 `.github/workflows/test.yml` (new)

Single workflow, single job, Windows runner, Python matrix `[3.10, 3.11, 3.12]`. Steps:

1. `actions/checkout@v4`
2. `astral-sh/setup-uv@v3` with `python-version` from the matrix (handles both uv and Python in one action; idiomatic for `uv`-based projects)
3. `uv sync --extra dev`
4. `uv run pytest -m "not integration"`

Triggers: `push` to `main`, `pull_request` to `main`. No release job.

Acceptance: a push to a feature branch triggers CI, all three matrix jobs pass, and the run shows up on GitHub Actions tab.

---

## 5. Verification plan

Run in this order:

1. **Local unit suite** — `pytest -m "not integration"` from repo root: 243 passing, 0 failing. Establishes baseline before any change.
2. **Local build** — `uv build` produces `dist/mt5_mcp-1.0.0-py3-none-any.whl` and `mt5_mcp-1.0.0.tar.gz` with the right metadata (verify with `python -m zipfile -l dist/mt5_mcp-1.0.0-py3-none-any.whl` to spot-check `METADATA`).
3. **Local install from wheel** — fresh Windows venv (e.g., `python -m venv %TEMP%\mt5-mcp-smoke && %TEMP%\mt5-mcp-smoke\Scripts\pip install dist\mt5_mcp-1.0.0-py3-none-any.whl`), then `%TEMP%\mt5-mcp-smoke\Scripts\python -m mt5_mcp doctor`. On Windows with a live terminal: 9× `[PASS]`. On a machine without MT5: clean error message, no Python tracebacks.
4. **CI smoke** — push a feature branch with `.github/workflows/test.yml`; confirm all three matrix jobs (3.10/3.11/3.12) pass on the Windows runner.
5. **Repo migration** — user creates `github.com/vincentwongso/mt5-mcp` (empty, public). I update the local `origin` URL via `git remote set-url`. The user then runs `git push -u origin main` and `git push origin v1.0.0` to populate the new repo. The new repo starts empty, so this is a normal push, not a force-push.
6. **PyPI publish** — user runs `uv publish` (after configuring credentials). Verify the project page at `pypi.org/project/mt5-mcp/` renders the README correctly, shows author `Vincent`, version `1.0.0`, and the three project URLs resolve.
7. **End-to-end smoke from PyPI** — fresh machine or fresh venv: `pip install mt5-mcp` → `python -m mt5_mcp doctor`. Closes the loop: a stranger can install and use this.
8. **Example config check** — paste `examples/clients/claude-desktop-stdio.json` (with paths adjusted) into a real Claude Desktop config; restart; confirm `mt5-mcp` appears in the tool list.

---

## 6. Open items requiring user action

These are explicitly out of the implementation plan because they touch shared state with credentials or external services:

1. **Create `github.com/vincentwongso/mt5-mcp`** as an empty public repo. I will not push until the user confirms the repo exists and instructs me to swap the remote.
2. **Verify `mt5-mcp` is available on PyPI.** If taken, fall back to a different name (`mt5-trading-mcp`, `mt5mcp-server`, `mt5-mcp-server` — listed in order of preference) and update `pyproject.toml` `name` field plus all README install instructions before publishing.
3. **Run `uv publish`** for the `1.0.0` artifact. The user runs this in their terminal; credentials never appear in this session.
4. **Optional: configure GitHub repo settings** — branch protection on `main`, default branch, Topics/About metadata, Security advisory settings. Not blocking for v1.0; can be done post-launch.

---

## 7. What is explicitly out of scope (for the record)

So future agents don't re-litigate:

- **Auto-generated docs site** — deferred to v1.1. The current architecture doc + README + CLAUDE.md is enough for a competent developer.
- **Plugin loader for third-party tools** — deferred to v1.1. `src/mt5_mcp/plugins/` stub exists but stays unwired.
- **All Phase 2 carryovers** — background TTL sweeper for idempotency, audit prune CLI, `pick_filling_mode` improvements. Revisit when reported.
- **All Phase 3 carryovers** — non-loopback HTTP bind, per-subscriber backpressure, dead-subscriber TTL sweeper. Revisit when reported. The README VPS section (4.2 §8) deliberately routes around the loopback restriction via SSH tunneling — that is the supported v1.0 deployment path for a remote MT5 terminal.
- **Test migration off `_tool_manager.get_tool().fn`** — blocked on FastMCP shipping a public sync accessor. No-op until upstream changes.
- **`LICENCE` → `LICENSE` rename** — non-blocking, irrelevant to PyPI metadata.
- **`CONTRIBUTING.md`** — non-blocking, can be added post-1.0 without a new phase.
- **Trusted Publishing GitHub Actions workflow** — deferred until the manual `uv publish` path is proven and a second release is in sight.
- **Telemetry, opt-in or otherwise** — architecture §16 q8 settled this: ship without telemetry, add later if there's demand.

---

## 8. Risks

1. **PyPI name collision.** `mt5-mcp` may already exist. Mitigation: §6 item 2 — fall back to `mt5-trading-mcp` or similar, update README + pyproject before publish. Cost: ~10 min of extra editing.
2. **GitHub Actions Windows runner cold-start time.** Windows runners are slower than Linux. Tests should still complete under 5 min for the full unit suite. If CI gets painful, we can drop to a single Python version or a Linux runner with `MetaTrader5` mocked at the dependency level — but defer that until it's actually painful.
3. **README drift between `README.md` and PyPI rendering.** PyPI uses `setuptools`/`hatchling` to render the README; some markdown features (relative links to other repo files) don't resolve correctly on PyPI. Mitigation: use absolute GitHub URLs for all internal links in the README. Verify post-publish in §5 step 6.
4. **First-time `uv publish` setup friction.** The user may need to create a PyPI account, generate an API token, and configure `~/.pypirc` or `UV_PUBLISH_TOKEN`. Cost: ~15 min one-time. Not a code risk, just calendar time.
