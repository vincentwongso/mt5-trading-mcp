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

Security fixes ship as patch releases. Only the current release on PyPI is actively maintained.

## Scope

`mt5-mcp` is **not** the security boundary. The broker's MetaTrader 5 server enforces hard limits — margin requirements, max-lot sizes, symbol permissions, account-level protections. Pre-flight checks in the policy engine (`max_notional_per_trade`, `max_daily_loss`, etc.) are UX guardrails to catch agent mistakes early, not security controls. They protect a misbehaving agent from itself; they do not protect against an attacker with terminal access.

The MCP runs locally in the customer's process tree. It has no cloud component, no telemetry, and no auto-update. Threats outside this scope — for example, compromise of the broker's MT5 server, theft of MT5 login credentials, OS-level keylogging or screen capture, or compromise of the agent runtime — are out of scope for `mt5-mcp` itself.

## What we consider in scope

Bug reports against any of the following will get a fix release:

- **Idempotency-replay correctness** — a request with the same `idempotency_key` returning a different result than the first call.
- **Audit-log integrity** — a mutating action that completes without a corresponding entry in the audit JSONL, or a forged/missing field in an audit entry.
- **Consent-flow integrity** — a retry passing `approval_confirmed=true` succeeding when the fields the engine validates (`symbol`, `side`, `type`, `volume`, `ticket`) don't match the original `ApprovalPreview`.
- **HTTP transport bearer-token check** — non-constant-time token comparison, or a path that bypasses the check.
- **Config-file loading** — a config that should be rejected (invalid type, missing required field) being silently accepted, or a path-traversal in any user-supplied path field.

## Out of scope

- Reports that require attacker-controlled access to the operator's machine (the local-first threat model assumes the operator is trusted).
- Reports against the upstream `MetaTrader5` Python library — file those with MetaQuotes.
- "Best practice" suggestions without a demonstrated bug (please open a regular issue or PR).
