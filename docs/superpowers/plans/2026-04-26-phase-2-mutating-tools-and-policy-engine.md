# Phase 2 — Mutating Tools + Policy Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four mutating MCP tools (`place_order`, `modify_order`, `cancel_order`, `close_position`) on top of a single `PolicyEngine` that handles preflight limits, consent gating, idempotency, and audit logging.

**Architecture:** A new `mt5_mcp.policy` package owns four small modules — `preflight`, `consent`, `idempotency`, `audit` — orchestrated behind a single `PolicyEngine.guard(...)` context-manager. Mutating tools keep the Phase-1 `@error_envelope` decorator and call `with ctx.policy.guard(...)` inside the body. Tools own their own gate-trigger logic (e.g. `modify_order`'s SL-widening rule); the engine handles the retry mechanism. Idempotency is SQLite (per-OS path via `platformdirs`), audit is append-only JSONL.

**Tech Stack:** Python 3.10+, `mcp[cli]`, `pydantic` v2, `MetaTrader5` (Windows-only, gated), `platformdirs` (NEW), `python-ulid` (NEW), `pytest` (no live terminal needed).

**Baseline:** commit `2fe9265` on `main` — 91 tests passing, zero deprecation warnings, all five Phase-1 carryover items closed. **Spec:** `docs/superpowers/specs/2026-04-26-phase-2-mutating-tools-and-policy-engine-design.md`.

---

## File Structure

Phase 2 modifies existing files and adds the `policy/` package + four new test files.

**New files:**
- `src/mt5_mcp/policy/__init__.py` — exports `PolicyEngine`, `PreflightInputs`
- `src/mt5_mcp/policy/preflight.py` — `check_preflight_limits(action, request, inputs, config)` returns `ErrorDetail | None`
- `src/mt5_mcp/policy/consent.py` — `ApprovalStore`, `validate_retry`, ULID minting
- `src/mt5_mcp/policy/idempotency.py` — `IdempotencyStore` (SQLite, WAL mode)
- `src/mt5_mcp/policy/audit.py` — `AuditLog` (JSONL append-only, size-based rotation)
- `src/mt5_mcp/policy/engine.py` — `PolicyEngine` + `GuardedExecution`
- `tests/test_policy_preflight.py`
- `tests/test_policy_consent.py`
- `tests/test_policy_idempotency.py`
- `tests/test_policy_audit.py`
- `tests/test_tools_place_order.py`
- `tests/test_tools_modify_order.py`
- `tests/test_tools_cancel_order.py`
- `tests/test_tools_close_position.py`

**Modified files:**
- `pyproject.toml` — add `platformdirs>=4.0`, `python-ulid>=2.0` to dependencies
- `src/mt5_mcp/types.py` — add `OrderRequest`, `ModifyOrderRequest`, `CancelOrderRequest`, `ClosePositionRequest`, `OrderResult`, `ApprovalPreview`
- `src/mt5_mcp/errors.py` — add factories: `invalid_approval_error`, `exceeds_local_limit_error`, `idempotency_diverged_error`, `invalid_ticket_error`
- `src/mt5_mcp/config.py` — extend `IdempotencyConfig`, `AuditConfig`; add `platformdirs` defaults; surface `policy.*` fields
- `src/mt5_mcp/adapter/conversions.py` — add `order_request_to_mt5_dict`, `order_result_from_mt5_response`
- `src/mt5_mcp/server.py` — instantiate `PolicyEngine` in `build_context()`, attach to `AppContext`
- `src/mt5_mcp/tools/orders.py` — add `place_order`, `modify_order`, `cancel_order`
- `src/mt5_mcp/tools/positions.py` — add `close_position`
- `tests/fakes.py` — add `FakeOrderSendResult`, extend `FakeMT5.order_send` (records request dicts in a list)
- `tests/conftest.py` — extend `_reset_app_context` to close engine resources
- `mt5-mcp-architecture.md` — reconcile §8.1/§8.2/§8.3/§8.4 with the spec
- `CLAUDE.md` — document the `ctx.policy.guard(...)` pattern; add new gotchas

**Rationale for splits:**
- Each `policy/*.py` module is independently testable (one concern per file). The engine sits on top and composes them; submodules know nothing of each other.
- Tool tests are split per tool because each one exercises distinct business rules (notional gate vs. SL-widening gate vs. ticket lookup vs. partial close).
- `tests/fakes.py` gains additions, never restructured — Phase 1 patterns are preserved.

---

## DAG Map (parallel-aware task ordering)

The user wants subagents to execute tasks in parallel where possible. The dependency graph below makes "what blocks what" explicit. Tasks within the same **wave** can run concurrently.

```
Wave 0 (sequential pre-flight): T0 baseline verification

Wave 1 (parallel — foundation, all independent of each other):
    T1  pyproject.toml deps           (touches: pyproject.toml)
    T2  types.py additions            (touches: src/mt5_mcp/types.py)
    T3  errors.py factories           (touches: src/mt5_mcp/errors.py)
    T4  config.py extensions          (touches: src/mt5_mcp/config.py)
    T5  fakes.py extensions           (touches: tests/fakes.py)
    T16 architecture-doc reconcile    (touches: mt5-mcp-architecture.md)

Wave 2 (parallel — adapter conversions; depends on T2):
    T6  conversions.py order helpers  (touches: src/mt5_mcp/adapter/conversions.py)

Wave 3 (parallel — policy submodules; depends on T2,T3,T4):
    T7  policy/idempotency.py         (touches: src/mt5_mcp/policy/{__init__,idempotency}.py)
    T8  policy/audit.py               (touches: src/mt5_mcp/policy/audit.py)
    T9  policy/consent.py             (touches: src/mt5_mcp/policy/consent.py)
    T10 policy/preflight.py           (touches: src/mt5_mcp/policy/preflight.py)

Wave 4 (sequential — engine assembly; depends on T7,T8,T9,T10):
    T11 policy/engine.py              (touches: src/mt5_mcp/policy/engine.py)

Wave 5 (sequential — wire into AppContext; depends on T11 + T4 + T5):
    T12 server.py integration         (touches: src/mt5_mcp/server.py, tests/conftest.py)

Wave 6 (parallel — tool implementations; depends on T12 + T6):
    T13 place_order                   (touches: src/mt5_mcp/tools/orders.py)
    T14 close_position                (touches: src/mt5_mcp/tools/positions.py)
    [T15 modify_order and T16 cancel_order also touch tools/orders.py;
     they run sequentially after T13 to avoid merge conflicts.]

Wave 7 (sequential after Wave 6 — same-file edits):
    T15 modify_order                  (touches: src/mt5_mcp/tools/orders.py)
    T16b cancel_order                 (touches: src/mt5_mcp/tools/orders.py)

Wave 8 (parallel — polish; depends on Wave 7):
    T17 doctor CLI smoke extension    (touches: src/mt5_mcp/cli/doctor.py)
    T18 CLAUDE.md update              (touches: CLAUDE.md)

Wave 9 (sequential — release):
    T19 final verification + tag      (no code; runs full suite, tags phase-2-complete, pushes)
```

**Notes for the dispatcher:**
- Tasks with disjoint file sets in the same wave are safe to fan out to subagents simultaneously.
- T15 and T16b both append to `tools/orders.py`; they share a file with T13. To avoid merge conflicts, run them after T13 lands. A coordinator that batches their diffs into one merge could parallelise them — but the simpler path is sequential.
- T16 (architecture doc) has no code dependency and can sit in any wave; placing it in Wave 1 keeps it out of the way.
- Each task's commit must run the full `pytest -q` before pushing — green is the gate.

---

## Implementation conventions

Applied throughout every task:

- **TDD**: write the failing test first, then the minimum code to pass it, then run the test, then commit.
- **Decimals only** — never `float`. Inputs from `MetaTrader5` come as `float`; convert with `Decimal(str(f))`.
- **Aware UTC datetimes only** in Pydantic models. The `_Base` validator rejects naive or non-UTC. `adapter/conversions.py::epoch_to_utc` is the only producer.
- **Hand-rolled fakes** in tests — no `unittest.mock.MagicMock`. Extend `FakeMT5` when a new RPC is needed.
- **`ctx = get_context()` as the first line** of every tool body (Phase-1 pattern). Tools take no `ctx` parameter.
- **`ctx.client.call(lambda m: m.X(...))`** for every mt5lib data RPC — never raw `ctx.client.mt5.X(...)` except for module-level constants like `m.ORDER_FILLING_IOC`.
- **Commit after each task** with Conventional Commits prefix: `feat:`, `test:`, `chore:`, `refactor:`, `docs:`. Running the full suite with `pytest -q` is part of the commit gate; commit only on green.
- **UTC-portable test epochs**: `int(datetime(YYYY, M, D, H, M, tzinfo=timezone.utc).timestamp())`. Naive `.timestamp()` is a portability bug.

---

## Task 0: Pre-flight verification of baseline

Establish that the baseline matches expectations before adding anything.

**Files:** none

- [ ] **Step 1: Confirm branch and baseline commit**

Run: `git status && git log --oneline -1`
Expected: clean working tree (or only `mt5-mcp-architecture.md` modified — Vincent's in-progress edit), HEAD at `2fe9265 refactor(phase-1): close five carryover items before Phase 2`.

- [ ] **Step 2: Run the full test suite**

Run: `py -m pytest -q`
Expected: `91 passed in <2s`, no warnings.

- [ ] **Step 3: Run with deprecation warnings as errors**

Run: `py -m pytest -W error::DeprecationWarning -q`
Expected: `91 passed`. If any new dep warning appears, stop and triage.

- [ ] **Step 4: Confirm doctor CLI succeeds against the live terminal** *(optional; skip on CI)*

Run: `python -m mt5_mcp doctor`
Expected: 8x `[PASS]`. Skip if no MT5 terminal — Phase-2 unit tests don't require it.

- [ ] **Step 5: No commit** — Wave 0 makes no changes.

---

## Task 1: Add `platformdirs` and `python-ulid` dependencies

**Wave 1 — parallel.** No code dependency.

**Files:**
- Modify: `pyproject.toml` (in the `dependencies` list under `[project]`)

- [ ] **Step 1: Add the two new dependencies**

In `pyproject.toml`, locate the `dependencies = [...]` block and append the two new pins:

```toml
dependencies = [
  "mcp[cli]>=1.12",
  "pydantic>=2.6",
  "watchdog>=4.0",
  "tomli>=2.0; python_version < '3.11'",
  "MetaTrader5>=5.0.45; platform_system == 'Windows'",
  "platformdirs>=4.0",
  "python-ulid>=2.0",
]
```

- [ ] **Step 2: Re-install in editable mode**

Run: `py -m pip install -e ".[dev]"`
Expected: installs `platformdirs` and `python-ulid` (or reports "already satisfied"); no errors.

- [ ] **Step 3: Verify imports**

Run: `py -c "import platformdirs, ulid; print(platformdirs.__version__, ulid.__version__ if hasattr(ulid, '__version__') else 'ok')"`
Expected: prints two versions, no ImportError.

- [ ] **Step 4: Run the suite to confirm no regression**

Run: `py -m pytest -q`
Expected: `91 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore(phase-2): add platformdirs and python-ulid deps"
```

---

## Task 2: Add Phase-2 Pydantic models to `types.py`

**Wave 1 — parallel.** No code dependency. (`platformdirs`/`ulid` from T1 are not imported here.)

**Files:**
- Modify: `src/mt5_mcp/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Write failing tests for the new models**

Append to `tests/test_types.py`:

```python
def test_order_request_rejects_float_volume():
    import pytest
    from pydantic import ValidationError
    from mt5_mcp.types import OrderRequest

    with pytest.raises(ValidationError):
        OrderRequest(symbol="EURUSD", side="buy", type="market", volume=0.1)


def test_order_request_market_allows_no_price():
    from mt5_mcp.types import OrderRequest

    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    assert req.price is None
    assert req.deviation == 10
    assert req.approval_confirmed is False


def test_order_result_replayed_defaults_false():
    from mt5_mcp.types import OrderResult

    r = OrderResult(success=True, ticket=42, action="place_order", symbol="EURUSD",
                    volume=Decimal("0.1"), price_filled=Decimal("1.0823"),
                    request_echo={"x": 1}, server_response_code=10009)
    assert r.replayed is False


def test_approval_preview_serialises_decimals_as_strings():
    import json
    from mt5_mcp.types import ApprovalPreview, Quote

    p = ApprovalPreview(
        request_id="01HX0000000000000000000000",
        expires_at=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
        summary="BUY 0.5 EURUSD @ market",
        action="place_order", symbol="EURUSD",
        notional=Decimal("54000.00"), estimated_margin=Decimal("540.00"),
        reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                              ask=Decimal("1.0824"),
                              time=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)),
        request_echo={"x": 1},
    )
    blob = json.loads(p.model_dump_json())
    assert blob["notional"] == "54000.00"
    assert blob["reference_quote"]["bid"] == "1.0823"


def test_modify_order_request_optional_fields_default_none():
    from mt5_mcp.types import ModifyOrderRequest

    r = ModifyOrderRequest(ticket=12345)
    assert r.sl is None and r.tp is None and r.price is None
    assert r.approval_confirmed is False


def test_cancel_order_request_no_approval_fields():
    from mt5_mcp.types import CancelOrderRequest

    r = CancelOrderRequest(ticket=12345)
    # cancel_order has NO approval fields by design (reduces exposure).
    assert not hasattr(r, "approval_confirmed")
    assert not hasattr(r, "approval_request_id")
```

- [ ] **Step 2: Run tests — expect failure (`ImportError`)**

Run: `py -m pytest tests/test_types.py -k "order_request or order_result or approval_preview or modify_order or cancel_order" -v`
Expected: ImportError on each new test (`OrderRequest`, `OrderResult`, etc. don't exist yet).

- [ ] **Step 3: Add the new models to `src/mt5_mcp/types.py`**

Append to the bottom of the file (after `TerminalInfo`):

```python
class OrderRequest(_Base):
    symbol: str
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop", "stop_limit"]
    volume: _DecimalStr
    price: _DecimalStr | None = None             # required for limit / stop / stop_limit
    stop_limit_price: _DecimalStr | None = None  # required for stop_limit only
    sl: _DecimalStr | None = None
    tp: _DecimalStr | None = None
    deviation: int = 10
    comment: str | None = None
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None


class ModifyOrderRequest(_Base):
    ticket: int
    sl: _DecimalStr | None = None
    tp: _DecimalStr | None = None
    price: _DecimalStr | None = None             # pending orders only
    expiration: datetime | None = None
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None


class CancelOrderRequest(_Base):
    ticket: int
    idempotency_key: str | None = None


class ClosePositionRequest(_Base):
    ticket: int
    volume: _DecimalStr | None = None            # None = close in full
    idempotency_key: str | None = None
    approval_confirmed: bool = False
    approval_request_id: str | None = None


class ApprovalPreview(_Base):
    request_id: str                              # ULID (canonical 26-char Crockford base32)
    expires_at: datetime
    summary: str
    action: Literal["place_order", "modify_order", "close_position"]
    symbol: str
    notional: _DecimalStr
    estimated_margin: _DecimalStr
    reference_quote: Quote
    request_echo: dict[str, Any]


class OrderResult(_Base):
    success: bool
    ticket: int | None
    action: str
    symbol: str
    volume: _DecimalStr
    price_filled: _DecimalStr | None
    request_echo: dict[str, Any]
    replayed: bool = False
    error: ErrorDetail | None = None
    server_response_code: int
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_types.py -v`
Expected: all 18 tests pass (12 existing + 6 new).

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/types.py tests/test_types.py
git commit -m "feat(phase-2): add OrderRequest/Result/Preview Pydantic models"
```

---

## Task 3: Add new error-code factories to `errors.py`

**Wave 1 — parallel.** No code dependency.

**Files:**
- Modify: `src/mt5_mcp/errors.py`
- Modify: `tests/test_errors.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_errors.py`:

```python
def test_invalid_approval_error():
    from mt5_mcp.errors import invalid_approval_error

    err = invalid_approval_error(reason="price drift exceeded 0.5%")
    assert err.code == "INVALID_APPROVAL"
    assert err.retryable is True
    assert err.requires_human is True
    assert err.details == {"reason": "price drift exceeded 0.5%"}


def test_exceeds_local_limit_error():
    from decimal import Decimal
    from mt5_mcp.errors import exceeds_local_limit_error

    err = exceeds_local_limit_error(
        limit_name="max_notional_per_trade",
        configured=Decimal("10000"),
        attempted=Decimal("25000"),
    )
    assert err.code == "EXCEEDS_LOCAL_LIMIT"
    assert err.retryable is False
    assert err.requires_human is True
    assert err.details["limit_name"] == "max_notional_per_trade"
    assert err.details["configured"] == "10000"
    assert err.details["attempted"] == "25000"


def test_idempotency_diverged_error():
    from mt5_mcp.errors import idempotency_diverged_error

    err = idempotency_diverged_error(key="01HX...", action="place_order")
    assert err.code == "IDEMPOTENCY_DIVERGED"
    assert err.retryable is False
    assert err.requires_human is True
    assert err.details == {"key": "01HX...", "action": "place_order"}


def test_invalid_ticket_error():
    from mt5_mcp.errors import invalid_ticket_error

    err = invalid_ticket_error(ticket=12345, kind="position")
    assert err.code == "INVALID_TICKET"
    assert err.retryable is False
    assert err.requires_human is False
    assert err.details == {"ticket": 12345, "kind": "position"}
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_errors.py -v`
Expected: 4 ImportErrors on the new factories.

- [ ] **Step 3: Add factories to `src/mt5_mcp/errors.py`**

Append to the bottom of the file (after `terminal_not_connected_error`):

```python
def invalid_approval_error(*, reason: str) -> ErrorDetail:
    """Approval-confirmed retry didn't match the stored preview."""
    return ErrorDetail(
        code="INVALID_APPROVAL",
        message=f"Approval rejected: {reason}",
        retryable=True,
        requires_human=True,
        details={"reason": reason},
    )


def exceeds_local_limit_error(
    *,
    limit_name: str,
    configured: Any,
    attempted: Any,
) -> ErrorDetail:
    """Pre-flight refusal — request would breach a configured local limit."""
    return ErrorDetail(
        code="EXCEEDS_LOCAL_LIMIT",
        message=(
            f"Request exceeds configured {limit_name}: attempted "
            f"{attempted}, configured {configured}."
        ),
        retryable=False,
        requires_human=True,
        details={
            "limit_name": limit_name,
            "configured": str(configured),
            "attempted": str(attempted),
        },
    )


def idempotency_diverged_error(*, key: str, action: str) -> ErrorDetail:
    """Same idempotency key, different request body — caller bug."""
    return ErrorDetail(
        code="IDEMPOTENCY_DIVERGED",
        message=(
            f"Idempotency key '{key}' was previously used for {action} with "
            "a different request body. Use a fresh key for distinct requests."
        ),
        retryable=False,
        requires_human=True,
        details={"key": key, "action": action},
    )


def invalid_ticket_error(*, ticket: int, kind: Literal["order", "position"]) -> ErrorDetail:
    """Ticket lookup failed — order/position doesn't exist."""
    return ErrorDetail(
        code="INVALID_TICKET",
        message=f"No {kind} with ticket {ticket}.",
        retryable=False,
        requires_human=False,
        details={"ticket": ticket, "kind": kind},
    )
```

Add `Literal` to the existing imports in this file:

```python
from typing import Any, Literal
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_errors.py -v`
Expected: 7 tests pass (3 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/errors.py tests/test_errors.py
git commit -m "feat(phase-2): add error factories for policy engine"
```

---

## Task 4: Extend `config.py` with platformdirs paths + Phase-2 fields

**Wave 1 — parallel.** No code dependency. (Imports `platformdirs` from T1; if running before T1's pip install, `platformdirs` will be missing — for parallel dispatch, T1 should run first OR these two tasks must be coordinated. **Recommended: T1 in Wave 0.5, then T4 in Wave 1.** For practical purposes treat T4 as Wave-1 with T1 already merged.)

**Files:**
- Modify: `src/mt5_mcp/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py`:

```python
def test_default_idempotency_path_uses_platformdirs():
    from mt5_mcp.config import Config

    cfg = Config()
    # Path should resolve under platformdirs.user_data_dir("mt5-mcp")
    p = cfg.idempotency.path
    assert p.endswith("idempotency.db") or p.endswith("idempotency.db".replace("/", "\\"))
    assert "mt5-mcp" in p


def test_default_audit_path_uses_platformdirs():
    from mt5_mcp.config import Config

    cfg = Config()
    p = cfg.audit.path
    assert p.endswith("audit.jsonl") or p.endswith("audit.jsonl".replace("/", "\\"))
    assert "mt5-mcp" in p


def test_idempotency_path_is_overridable_in_toml(tmp_path):
    import textwrap
    from mt5_mcp.config import load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [idempotency]
        path = "/custom/path/idem.db"
        ttl_seconds = 3600

        [audit]
        path = "/custom/path/audit.jsonl"
        max_bytes = 1048576
    """).strip())
    cfg = load_config(cfg_file)
    assert cfg.idempotency.path == "/custom/path/idem.db"
    assert cfg.idempotency.ttl_seconds == 3600
    assert cfg.audit.path == "/custom/path/audit.jsonl"
    assert cfg.audit.max_bytes == 1048576
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_config.py -v -k "platformdirs or overridable"`
Expected: AttributeError (`IdempotencySection` has no `path`) and the override test fails for the same reason.

- [ ] **Step 3: Update `IdempotencySection` and `AuditSection`**

Replace the existing `IdempotencySection` and `AuditSection` classes in `src/mt5_mcp/config.py`:

```python
def _user_data_path(filename: str) -> str:
    """Per-OS default path under platformdirs.user_data_dir('mt5-mcp')."""
    from platformdirs import user_data_dir

    return str(Path(user_data_dir("mt5-mcp")) / filename)


class IdempotencySection(_Sub):
    path: str = Field(default_factory=lambda: _user_data_path("idempotency.db"))
    ttl_seconds: PositiveInt = 86_400


class AuditSection(_Sub):
    path: str = Field(default_factory=lambda: _user_data_path("audit.jsonl"))
    max_bytes: PositiveInt = 10_485_760
```

The `_user_data_path` helper goes near the top of the file (after the `_Sub` base class). The `Field(default_factory=...)` indirection avoids importing `platformdirs` at module-import time (it imports only when `Config()` is instantiated).

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_config.py -v`
Expected: all tests pass (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/config.py tests/test_config.py
git commit -m "feat(phase-2): default idempotency/audit paths via platformdirs"
```

---

## Task 5: Extend `tests/fakes.py` with `FakeOrderSendResult` and `order_send`

**Wave 1 — parallel.** No code dependency.

**Files:**
- Modify: `tests/fakes.py`

- [ ] **Step 1: Add `FakeOrderSendResult` dataclass**

Append in `tests/fakes.py` after the existing `FakeDeal` dataclass (around line 145):

```python
@dataclass
class FakeOrderSendResult:
    """Mimics the NamedTuple `mt5.order_send()` returns."""
    retcode: int = TRADE_RETCODE_DONE          # 10009 = DONE
    order: int = 0                             # ticket of the created/affected order
    deal: int = 0                              # ticket of the resulting deal (market orders)
    volume: float = 0.0
    price: float = 0.0
    comment: str = ""
    request_id: int = 0
    external_id: str = ""
```

`TRADE_RETCODE_DONE = 10009` is already imported at the top of `fakes.py`; if not, add it to the constants block.

- [ ] **Step 2: Add an `_order_send` slot and `order_send()` method on `FakeMT5`**

Inside the `FakeMT5` class body, add the slot after `_history_deals_get`:

```python
    _order_send: FakeOrderSendResult | None = field(default_factory=FakeOrderSendResult)
    # `order_send_calls` records the request dict passed to each order_send
    # call, in order. Tests use `len()` to count and indexing to inspect.
    order_send_calls: list[dict[str, Any]] = field(default_factory=list)
```

And add the method (place it next to `last_error`):

```python
    def order_send(self, request: dict[str, Any]) -> FakeOrderSendResult | None:
        self._bump("order_send")
        # Defensive copy — tests may mutate the dict afterwards.
        self.order_send_calls.append(dict(request))
        return self._order_send
```

- [ ] **Step 3: No test runs in isolation** — `tests/fakes.py` is exercised by every other test. Confirm:

Run: `py -m pytest -q`
Expected: `91 passed`. The new fields are unused by Phase-1 tests, so behaviour is unchanged.

- [ ] **Step 4: Commit**

```bash
git add tests/fakes.py
git commit -m "test(phase-2): extend FakeMT5 with order_send slot and call recorder"
```

---

## Task 6: Add `order_request_to_mt5_dict` and `order_result_from_mt5_response` to `conversions.py`

**Wave 2 — depends on T2 (types) + T5 (FakeOrderSendResult for tests).**

**Files:**
- Modify: `src/mt5_mcp/adapter/conversions.py`
- Modify: `tests/test_adapter_conversions.py`

- [ ] **Step 1: Inspect existing constants to wire correctly**

Run: `grep -n "POSITION_TYPE\|ORDER_TYPE\|TRADE_ACTION" C:/projects/mt5-trading-mcp/src/mt5_mcp/adapter/conversions.py || true`
The mt5lib constants we map to are: `mt5.ORDER_TYPE_BUY/SELL` for market, `mt5.ORDER_TYPE_BUY_LIMIT/SELL_LIMIT/BUY_STOP/SELL_STOP/BUY_STOP_LIMIT/SELL_STOP_LIMIT` for pendings; trade action is `mt5.TRADE_ACTION_DEAL` for market and `mt5.TRADE_ACTION_PENDING` for pendings.

The fake module re-exposes the constants we need; the real module exposes them at module scope. The conversion function takes the live `mt5` module as an argument so tests can pass `FakeMT5`.

- [ ] **Step 2: Write failing tests**

Append to `tests/test_adapter_conversions.py`:

```python
def test_order_request_to_mt5_dict_market_buy(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.10"), deviation=15)
    info = FakeSymbolInfo(name="EURUSD", point=0.00001, digits=5,
                         filling_mode=1 | 2)
    out = order_request_to_mt5_dict(
        req, symbol_info=info, filling_mode=fake_mt5.ORDER_FILLING_IOC,
        price=Decimal("1.0824"), mt5=fake_mt5,
    )
    assert out["action"] == fake_mt5.TRADE_ACTION_DEAL  # set in step 3
    assert out["symbol"] == "EURUSD"
    assert out["volume"] == 0.10
    assert out["type"] == fake_mt5.ORDER_TYPE_BUY       # set in step 3
    assert out["price"] == 1.0824
    assert out["deviation"] == 15
    assert out["type_filling"] == fake_mt5.ORDER_FILLING_IOC


def test_order_request_to_mt5_dict_limit_sell_includes_sl_tp(fake_mt5):
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_request_to_mt5_dict
    from mt5_mcp.types import OrderRequest
    from tests.fakes import FakeSymbolInfo

    req = OrderRequest(symbol="EURUSD", side="sell", type="limit",
                       volume=Decimal("0.50"), price=Decimal("1.0900"),
                       sl=Decimal("1.0950"), tp=Decimal("1.0850"),
                       comment="strat-1")
    info = FakeSymbolInfo()
    out = order_request_to_mt5_dict(
        req, symbol_info=info, filling_mode=fake_mt5.ORDER_FILLING_RETURN,
        price=Decimal("1.0900"), mt5=fake_mt5,
    )
    assert out["action"] == fake_mt5.TRADE_ACTION_PENDING  # set in step 3
    assert out["type"] == fake_mt5.ORDER_TYPE_SELL_LIMIT
    assert out["sl"] == 1.0950
    assert out["tp"] == 1.0850
    assert out["comment"] == "strat-1"


def test_order_result_from_mt5_response_filled():
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_result_from_mt5_response
    from tests.fakes import FakeOrderSendResult, TRADE_RETCODE_DONE

    raw = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE, order=12345, deal=999,
                              volume=0.1, price=1.0824)
    result = order_result_from_mt5_response(
        raw, action="place_order", symbol="EURUSD",
        request_volume=Decimal("0.1"),
        request_echo={"symbol": "EURUSD"},
    )
    assert result.success is True
    assert result.ticket == 12345
    assert result.action == "place_order"
    assert result.price_filled == Decimal("1.0824")
    assert result.server_response_code == TRADE_RETCODE_DONE
    assert result.error is None


def test_order_result_from_mt5_response_rejected():
    from decimal import Decimal
    from mt5_mcp.adapter.conversions import order_result_from_mt5_response
    from tests.fakes import FakeOrderSendResult, TRADE_RETCODE_REJECT

    raw = FakeOrderSendResult(retcode=TRADE_RETCODE_REJECT, comment="server says no")
    result = order_result_from_mt5_response(
        raw, action="place_order", symbol="EURUSD",
        request_volume=Decimal("0.1"),
        request_echo={"symbol": "EURUSD"},
    )
    assert result.success is False
    assert result.ticket is None
    assert result.error is not None
    assert result.error.code == "REJECTED_BY_SERVER"
    assert result.server_response_code == TRADE_RETCODE_REJECT
```

- [ ] **Step 3: Add the two helpers to `src/mt5_mcp/adapter/conversions.py`**

Append at the bottom of the file:

```python
# Map our string side+type to mt5lib's ORDER_TYPE_* enums and TRADE_ACTION_*.
def _resolve_order_type(mt5: Any, side: str, type_: str) -> int:
    table = {
        ("buy",  "market"):     mt5.ORDER_TYPE_BUY,
        ("sell", "market"):     mt5.ORDER_TYPE_SELL,
        ("buy",  "limit"):      mt5.ORDER_TYPE_BUY_LIMIT,
        ("sell", "limit"):      mt5.ORDER_TYPE_SELL_LIMIT,
        ("buy",  "stop"):       mt5.ORDER_TYPE_BUY_STOP,
        ("sell", "stop"):       mt5.ORDER_TYPE_SELL_STOP,
        ("buy",  "stop_limit"): mt5.ORDER_TYPE_BUY_STOP_LIMIT,
        ("sell", "stop_limit"): mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }
    return table[(side, type_)]


def order_request_to_mt5_dict(
    req: "OrderRequest",
    *,
    symbol_info: Any,
    filling_mode: int,
    price: Decimal,
    mt5: Any,
) -> dict[str, Any]:
    """Build the dict mt5.order_send() expects.

    `price` is the resolved limit/stop or current ask/bid for market orders.
    `filling_mode` is the resolved ORDER_FILLING_* int from SymbolPrep.
    """
    action = mt5.TRADE_ACTION_DEAL if req.type == "market" else mt5.TRADE_ACTION_PENDING
    out: dict[str, Any] = {
        "action": action,
        "symbol": req.symbol,
        "volume": float(req.volume),
        "type": _resolve_order_type(mt5, req.side, req.type),
        "price": float(price),
        "deviation": int(req.deviation),
        "type_filling": int(filling_mode),
        "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
        "magic": 0,
    }
    if req.stop_limit_price is not None:
        out["stoplimit"] = float(req.stop_limit_price)
    if req.sl is not None:
        out["sl"] = float(req.sl)
    if req.tp is not None:
        out["tp"] = float(req.tp)
    if req.comment:
        out["comment"] = req.comment
    return out


def order_result_from_mt5_response(
    raw: Any,
    *,
    action: str,
    symbol: str,
    request_volume: Decimal,
    request_echo: dict[str, Any],
) -> "OrderResult":
    """Convert mt5.order_send()'s return into a typed OrderResult."""
    from mt5_mcp.errors import error_for_retcode
    from mt5_mcp.types import OrderResult
    from tests.fakes import TRADE_RETCODE_DONE  # safe at import-time? See note.

    retcode = int(raw.retcode)
    success = retcode == 10009  # TRADE_RETCODE_DONE — same value in real lib
    error = None if success else error_for_retcode(retcode, message=str(raw.comment or ""))
    return OrderResult(
        success=success,
        ticket=int(raw.order) if success and raw.order else None,
        action=action,
        symbol=symbol,
        volume=request_volume,
        price_filled=Decimal(str(raw.price)) if success and raw.price else None,
        request_echo=request_echo,
        replayed=False,
        error=error,
        server_response_code=retcode,
    )
```

**Important:** the inline `from tests.fakes import TRADE_RETCODE_DONE` in step 3 above is a copy-paste hazard. Replace it with the literal `10009` value as shown — production code must NOT import from `tests.`. The hardcoded `10009` matches mt5lib's published constant.

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_adapter_conversions.py -v`
Expected: existing tests + 4 new pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/adapter/conversions.py tests/test_adapter_conversions.py
git commit -m "feat(phase-2): add order_request/result conversions"
```

---

## Task 16-arch: Reconcile `mt5-mcp-architecture.md` §8.* with the spec

**Wave 1 — parallel.** No code dependency. Pure documentation. Run any time before T19.

**Files:**
- Modify: `mt5-mcp-architecture.md`

- [ ] **Step 1: Replace §8.1 (consent gate)**

Find the existing §8.1 (lines 335-365 in the current file). Replace its body with:

```markdown
### 8.1 Consent gate

Mutating tools emit `requires_approval` when the request exceeds `policy.auto_approve_notional`. The MCP returns a structured `ApprovalPreview` — the agent obtains consent (e.g. via 1Password biometric in OpenClaw), then retries with `approval_confirmed: true` and the same `approval_request_id`.

```python
# Returned when over auto-approve threshold:
{
  "request_id": "01HX...",
  "expires_at": "2026-04-21T10:35:00Z",
  "summary": "BUY 0.5 EURUSD @ market (~$54000 USD)",
  "action": "place_order",
  "symbol": "EURUSD",
  "notional": "54000.00",
  "estimated_margin": "540.00",
  "reference_quote": {"symbol": "EURUSD", "bid": "1.0823", "ask": "1.0824",
                      "time": "2026-04-21T10:30:00Z"},
  "request_echo": {...}
}

# Agent retries with approval_confirmed:
{
  "tool": "place_order",
  "arguments": {
    ...,
    "approval_confirmed": true,
    "approval_request_id": "01HX..."
  }
}
```

**The consent gate is a UX/policy affordance, not a cryptographic control.** Real authentication lives at the transport layer — the OS process boundary for stdio, Tailscale's WireGuard node identity for HTTP. The MCP only verifies:

- The `approval_request_id` matches a stored, un-expired preview.
- The retry's identical fields (action / symbol / side / type / volume / ticket) match the preview.
- The retry's price is within `max(0.5%, deviation_points × point)` of the stored `reference_quote`.

On mismatch the MCP returns `INVALID_APPROVAL`. This protects against prompt-injection "bait and switch" attacks where an agent might trick a human into approving trade A but submit trade B.

Agent runtimes are free to layer additional authentication (biometrics, multi-person approval, hardware tokens) on top of the simple flag.
```

- [ ] **Step 2: Rename §8.2 to "Pre-flight limits" with non-security framing**

Replace the body of §8.2 with:

```markdown
### 8.2 Pre-flight limits

**These are not security controls.** The broker's MT5 server enforces per-trade, per-account, and leverage limits server-side; any trade exceeding broker limits gets rejected there regardless of what the MCP allows.

The MCP's pre-flight checks exist for UX: catching obviously invalid trades locally (~1 ms) gives the agent immediate feedback instead of a ~200 ms round-trip to a `REJECTED_BY_SERVER`.

Hard refusals (no `approval_confirmed` overrides these):

- `volume * price > policy.max_notional_per_trade`
- Symbol in `symbols.denylist`
- Symbol not in `symbols.allowlist` (when allowlist is non-empty)
- Daily realised P&L would breach `policy.max_daily_loss` (place_order only)
- Realised loss on close > `policy.max_realised_loss_per_close` (close_position only)

The daily P&L day boundary is **broker-server-day** — derived from the cached `broker_offset_minutes` set at `MT5Client.connect()`. P&L is `sum(deal.profit + deal.swap + deal.commission)` over `mt5.history_deals_get(broker_day_start, broker_now)`.
```

- [ ] **Step 3: Update §8.3 to mention platformdirs and divergence**

Replace the body of §8.3 with:

```markdown
### 8.3 Idempotency

Every mutating tool accepts an optional `idempotency_key`. If supplied:

- First call with this key executes normally; the resulting `OrderResult` is cached.
- Subsequent calls with the same key AND same canonical request hash within `idempotency.ttl_seconds` return the cached result with `replayed: true`.
- Same key, **different** request hash → `IDEMPOTENCY_DIVERGED` error. This surfaces caller bugs (e.g. forgetting to vary the key between distinct trades) instead of silently masking them.

Stored in a small SQLite database at `<user_data>/idempotency.db` (per-OS path via `platformdirs`; overridable in `config.toml` under `[idempotency] path`).

Without a key, no caching; agents are encouraged to supply UUIDv4s. Without one, retries after a network timeout could double-execute.
```

- [ ] **Step 4: Update §8.4 with the action enum and rotation semantics**

Replace the body of §8.4 with:

```markdown
### 8.4 Audit log

Every tool call appends one JSONL line to `<user_data>/audit.jsonl` (per-OS path via `platformdirs`; overridable in `config.toml` under `[audit] path`).

```json
{"ts": "2026-04-26T10:30:00Z", "tool": "place_order", "action": "executed",
 "request": {...}, "result_status": "filled", "ticket": 12345,
 "duration_ms": 142, "approval_request_id": null,
 "idempotency_key": "01HX...", "request_hash": "sha256:..."}
```

`action` is one of: `executed`, `requires_approval`, `replay`, `preflight_refused`, `invalid_approval`, `idempotency_diverged`, `error`, `called` (read-only tools log only this).

Mutating-tool events log the full request and result. Read-only events log only the call shape — result bodies would dominate disk on tight loops.

Rotation: when `os.path.getsize(audit.path) > audit.max_bytes`, the file is renamed to `audit.jsonl.<unix_epoch>` and a fresh handle opened. No compression; rotated files persist on disk indefinitely (operator's choice when to archive).

Customer can `tail -f` (`Get-Content -Wait` on Windows) the audit log to watch their agent in real time. Useful for debugging and for compliance reviews.
```

- [ ] **Step 5: Run the suite to confirm doc-only edits don't break anything**

Run: `py -m pytest -q`
Expected: still `91 passed` (or whatever is current at this wave's merge point).

- [ ] **Step 6: Commit**

```bash
git add mt5-mcp-architecture.md
git commit -m "docs(phase-2): reconcile §8.* with spec (HMAC removed, soft→pre-flight)"
```

---

## Task 7: Implement `policy/idempotency.py` (SQLite store)

**Wave 3 — parallel.** Depends on T2 (types) + T3 (errors). Can run alongside T8/T9/T10.

**Files:**
- Create: `src/mt5_mcp/policy/__init__.py`
- Create: `src/mt5_mcp/policy/idempotency.py`
- Create: `tests/test_policy_idempotency.py`

- [ ] **Step 1: Create `src/mt5_mcp/policy/__init__.py` (empty placeholder)**

```python
"""Policy engine: preflight + consent + idempotency + audit."""
```

The package's public exports (`PolicyEngine`, `PreflightInputs`) are added in T11 once the submodules exist.

- [ ] **Step 2: Write failing tests**

Create `tests/test_policy_idempotency.py`:

```python
"""IdempotencyStore — SQLite-backed cache for mutating-tool replays."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.policy.idempotency import IdempotencyStore


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyStore:
    s = IdempotencyStore(path=tmp_path / "idem.db", ttl_seconds=3600)
    yield s
    s.close()


def test_no_key_no_cache(store: IdempotencyStore):
    # Without a key, lookup returns None and put is a no-op.
    assert store.lookup(key=None, action="place_order", request_hash="abc") is None
    store.put(key=None, action="place_order", request_hash="abc",
              result_json='{"ticket":1}')
    assert store.lookup(key=None, action="place_order", request_hash="abc") is None


def test_fresh_put_then_replay(store: IdempotencyStore):
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42,"replayed":false}')
    hit = store.lookup(key="k1", action="place_order", request_hash="hash-1")
    assert hit == ("hit", '{"ticket":42,"replayed":false}')


def test_same_key_different_hash_is_divergent(store: IdempotencyStore):
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    hit = store.lookup(key="k1", action="place_order", request_hash="hash-2")
    assert hit == ("diverged", None)


def test_lookup_evicts_expired_entries(tmp_path: Path):
    s = IdempotencyStore(path=tmp_path / "idem.db", ttl_seconds=1)
    s.put(key="k1", action="place_order", request_hash="hash-1",
          result_json='{"ticket":42}')
    time.sleep(1.1)
    # Expired — lookup returns None and the row is deleted in-band.
    assert s.lookup(key="k1", action="place_order", request_hash="hash-1") is None
    # Re-inserting under the same key is allowed (the old row is gone).
    s.put(key="k1", action="place_order", request_hash="hash-2",
          result_json='{"ticket":99}')
    assert s.lookup(key="k1", action="place_order", request_hash="hash-2") \
           == ("hit", '{"ticket":99}')
    s.close()


def test_lookup_scope_is_action_specific(store: IdempotencyStore):
    # Same key on a different action is not a match — actions partition the namespace.
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    assert store.lookup(key="k1", action="close_position", request_hash="hash-1") is None


def test_persists_across_reopen(tmp_path: Path):
    p = tmp_path / "idem.db"
    s1 = IdempotencyStore(path=p, ttl_seconds=3600)
    s1.put(key="k1", action="place_order", request_hash="hash-1",
           result_json='{"ticket":42}')
    s1.close()
    s2 = IdempotencyStore(path=p, ttl_seconds=3600)
    assert s2.lookup(key="k1", action="place_order", request_hash="hash-1") \
           == ("hit", '{"ticket":42}')
    s2.close()
```

- [ ] **Step 3: Run tests — expect failure**

Run: `py -m pytest tests/test_policy_idempotency.py -v`
Expected: ImportError on `mt5_mcp.policy.idempotency`.

- [ ] **Step 4: Implement `src/mt5_mcp/policy/idempotency.py`**

```python
"""SQLite-backed idempotency cache for mutating-tool replays.

Schema: one row per (key, action) pair. Lookups are scoped by action so
the same key can be re-used across different tool kinds without colliding.
Same-key-same-hash → replay; same-key-different-hash → divergent (caller bug).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal


logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency (
    key             TEXT NOT NULL,
    action          TEXT NOT NULL,
    request_hash    TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    PRIMARY KEY (key, action)
);
CREATE INDEX IF NOT EXISTS idx_expires_at ON idempotency(expires_at);
"""


LookupResult = tuple[Literal["hit", "diverged"], str | None]


class IdempotencyStore:
    def __init__(self, *, path: Path | str, ttl_seconds: int) -> None:
        self._path = Path(path)
        self._ttl = int(ttl_seconds)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def lookup(
        self, *, key: str | None, action: str, request_hash: str
    ) -> LookupResult | None:
        """Return ('hit', result_json) on replay, ('diverged', None) on key
        collision, or None if no cache entry exists.

        Evicts expired rows for the (key, action) pair in-band.
        """
        if key is None:
            return None
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "SELECT request_hash, result_json, expires_at "
                "FROM idempotency WHERE key = ? AND action = ?",
                (key, action),
            )
            row = cur.fetchone()
            if row is None:
                return None
            stored_hash, result_json, expires_at = row
            if expires_at < now:
                self._conn.execute(
                    "DELETE FROM idempotency WHERE key = ? AND action = ?",
                    (key, action),
                )
                self._conn.commit()
                return None
            if stored_hash == request_hash:
                return ("hit", result_json)
            return ("diverged", None)

    def put(
        self,
        *,
        key: str | None,
        action: str,
        request_hash: str,
        result_json: str,
    ) -> None:
        """Cache `result_json` under (key, action). No-op if key is None."""
        if key is None:
            return
        now = int(time.time())
        expires_at = now + self._ttl
        with self._lock:
            self._conn.execute(
                "INSERT INTO idempotency "
                "(key, action, request_hash, result_json, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key, action) DO UPDATE SET "
                "request_hash = excluded.request_hash, "
                "result_json = excluded.result_json, "
                "created_at = excluded.created_at, "
                "expires_at = excluded.expires_at",
                (key, action, request_hash, result_json, now, expires_at),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
```

- [ ] **Step 5: Run tests — expect pass**

Run: `py -m pytest tests/test_policy_idempotency.py -v`
Expected: 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/policy/__init__.py src/mt5_mcp/policy/idempotency.py tests/test_policy_idempotency.py
git commit -m "feat(phase-2): add SQLite-backed idempotency store"
```

---

## Task 8: Implement `policy/audit.py` (JSONL append-only with rotation)

**Wave 3 — parallel.** No dependency on T7. Can run alongside T7/T9/T10.

**Files:**
- Create: `src/mt5_mcp/policy/audit.py`
- Create: `tests/test_policy_audit.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_policy_audit.py`:

```python
"""AuditLog — JSONL append-only with size-based rotation."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from mt5_mcp.policy.audit import AuditLog


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=1024)
    yield a
    a.close()


def test_writes_one_jsonl_line_per_event(audit: AuditLog, tmp_path: Path):
    audit.write({"tool": "place_order", "action": "executed", "ticket": 42})
    audit.write({"tool": "get_positions", "action": "called"})
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ticket"] == 42
    assert json.loads(lines[1])["action"] == "called"


def test_event_includes_iso_utc_timestamp(audit: AuditLog, tmp_path: Path):
    audit.write({"tool": "ping", "action": "called"})
    line = (tmp_path / "audit.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert "ts" in rec
    # ISO 8601 with explicit UTC suffix.
    assert rec["ts"].endswith("Z") or rec["ts"].endswith("+00:00")


def test_rotates_when_size_exceeds_max_bytes(tmp_path: Path):
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=200)
    # Write enough events to cross the threshold.
    for i in range(20):
        a.write({"tool": "x", "action": "called", "i": i, "padding": "abcdefghij" * 3})
    a.close()

    files = sorted(tmp_path.iterdir())
    rotated = [f for f in files if f.name.startswith("audit.jsonl.")]
    assert len(rotated) >= 1, f"expected rotation, found: {[f.name for f in files]}"
    # Current audit.jsonl exists and has fewer events than the original write count.
    current = (tmp_path / "audit.jsonl").read_text().splitlines()
    rotated_lines = sum(len(f.read_text().splitlines()) for f in rotated)
    assert len(current) + rotated_lines == 20


def test_concurrent_writers_serialise_correctly(tmp_path: Path):
    a = AuditLog(path=tmp_path / "audit.jsonl", max_bytes=1_000_000)
    n_threads = 8
    n_per = 50

    def worker(worker_id: int):
        for i in range(n_per):
            a.write({"tool": "x", "action": "called", "wid": worker_id, "i": i})

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    a.close()

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == n_threads * n_per
    # Every line must be valid JSON (no torn writes).
    for ln in lines:
        json.loads(ln)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_policy_audit.py -v`
Expected: ImportError on `mt5_mcp.policy.audit`.

- [ ] **Step 3: Implement `src/mt5_mcp/policy/audit.py`**

```python
"""Append-only JSONL audit log with size-based rotation.

One file handle per process; an RLock guards the write+rotate transition.
Rotation renames the current file to `audit.jsonl.<unix_epoch>` and opens
a fresh handle. No compression — operators rotate or archive manually.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, *, path: Path | str, max_bytes: int) -> None:
        self._path = Path(path)
        self._max_bytes = int(max_bytes)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp: io.TextIOWrapper | None = None
        self._open()

    def _open(self) -> None:
        # Line-buffered text mode so each write is flushed to the OS without
        # an explicit .flush() call. UTF-8 on every platform.
        self._fp = open(self._path, "a", encoding="utf-8", buffering=1)

    def _close_handle(self) -> None:
        if self._fp is not None:
            try:
                self._fp.close()
            finally:
                self._fp = None

    def _rotate_if_needed(self) -> None:
        try:
            size = os.path.getsize(self._path)
        except FileNotFoundError:
            return
        if size < self._max_bytes:
            return
        self._close_handle()
        rotated = self._path.with_name(f"{self._path.name}.{int(time.time())}")
        # If two writes race past the size check before either rotates, the
        # second rename target may already exist — fall back to a counter.
        suffix = 0
        candidate = rotated
        while candidate.exists():
            suffix += 1
            candidate = self._path.with_name(f"{self._path.name}.{int(time.time())}.{suffix}")
        os.replace(self._path, candidate)
        logger.info("audit log rotated: %s -> %s", self._path, candidate)
        self._open()

    def write(self, event: dict[str, Any]) -> None:
        """Append one JSONL event. A 'ts' field is added automatically."""
        record = {"ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                  **event}
        line = json.dumps(record, separators=(",", ":"), default=str)
        with self._lock:
            if self._fp is None:
                self._open()
            self._fp.write(line + "\n")
            self._rotate_if_needed()

    def close(self) -> None:
        with self._lock:
            self._close_handle()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_policy_audit.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/policy/audit.py tests/test_policy_audit.py
git commit -m "feat(phase-2): add JSONL audit log with size-based rotation"
```

---

## Task 9: Implement `policy/consent.py` (preview store + retry validation)

**Wave 3 — parallel.** Depends on T2 (types). Can run alongside T7/T8/T10.

**Files:**
- Create: `src/mt5_mcp/policy/consent.py`
- Create: `tests/test_policy_consent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_policy_consent.py`:

```python
"""ApprovalStore — in-memory preview cache + retry-validation logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mt5_mcp.policy.consent import ApprovalStore, validate_retry
from mt5_mcp.types import ApprovalPreview, OrderRequest, Quote


def _preview(*, request_id: str, side="buy", volume="0.5",
             ref_bid="1.0823", ref_ask="1.0824",
             expires_in_seconds: int = 300) -> ApprovalPreview:
    now = datetime.now(timezone.utc)
    return ApprovalPreview(
        request_id=request_id,
        expires_at=now + timedelta(seconds=expires_in_seconds),
        summary="BUY 0.5 EURUSD @ market (~$54000 USD)",
        action="place_order", symbol="EURUSD",
        notional=Decimal("54000"), estimated_margin=Decimal("540"),
        reference_quote=Quote(symbol="EURUSD", bid=Decimal(ref_bid),
                              ask=Decimal(ref_ask), time=now),
        request_echo={"symbol": "EURUSD", "side": side, "type": "market",
                      "volume": volume, "deviation": 10},
    )


def test_store_and_pop_roundtrip():
    s = ApprovalStore()
    p = _preview(request_id="01HX0000000000000000000001")
    s.put(p)
    out = s.pop("01HX0000000000000000000001")
    assert out is p
    # Preview is consumed on retrieval — single-use.
    assert s.pop("01HX0000000000000000000001") is None


def test_store_evicts_expired_on_pop():
    s = ApprovalStore()
    p = _preview(request_id="01HX0000000000000000000002", expires_in_seconds=-1)
    s.put(p)
    assert s.pop("01HX0000000000000000000002") is None  # expired → treated as missing


def test_validate_retry_accepts_matching_request():
    p = _preview(request_id="01HX0000000000000000000003")
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=10,
                       approval_confirmed=True, approval_request_id=p.request_id)
    point = Decimal("0.00001")
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"), point=point)
    assert err is None


def test_validate_retry_rejects_volume_mismatch():
    p = _preview(request_id="01HX0000000000000000000004", volume="0.5")
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("1.0"), approval_confirmed=True,
                       approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "volume" in err.details["reason"].lower()


def test_validate_retry_rejects_price_drift_beyond_tolerance():
    # Reference ask was 1.0824. Drift > 0.5% AND > deviation (10 points = 0.0001).
    # 0.5% of 1.0824 = 0.0054; 10 points = 0.0001. Tolerance = max(0.0054, 0.0001) = 0.0054.
    # Current price 1.10 is 0.0176 above ref → exceeds tolerance.
    p = _preview(request_id="01HX0000000000000000000005")
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=10,
                       approval_confirmed=True, approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.10"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "price" in err.details["reason"].lower()


def test_validate_retry_allows_drift_within_deviation_when_pct_tighter():
    # Cheap symbol where 0.5% is tiny but deviation is generous.
    # ref_ask = 0.5; 0.5% of 0.5 = 0.0025; deviation=100 points × point=0.001 → 0.1.
    # Tolerance is max(0.0025, 0.1) = 0.1. Drift 0.05 is within.
    p = _preview(request_id="01HX0000000000000000000006",
                 ref_bid="0.499", ref_ask="0.500")
    req = OrderRequest(symbol="X", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=100,
                       approval_confirmed=True, approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("0.55"),
                         point=Decimal("0.001"))
    assert err is None  # 100 points × 0.001 = 0.1 tolerance dominates


def test_validate_retry_rejects_expired_preview():
    p = _preview(request_id="01HX0000000000000000000007", expires_in_seconds=-1)
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"), approval_confirmed=True,
                       approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "expired" in err.details["reason"].lower()


def test_new_request_id_format():
    from mt5_mcp.policy.consent import new_request_id

    rid = new_request_id()
    assert isinstance(rid, str)
    assert len(rid) == 26  # canonical ULID length (Crockford base32, 128 bits)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_policy_consent.py -v`
Expected: ImportError on `mt5_mcp.policy.consent`.

- [ ] **Step 3: Implement `src/mt5_mcp/policy/consent.py`**

```python
"""Approval-preview store and retry-validation rules.

The store is in-memory: previews live for at most a few minutes and a
process restart legitimately invalidates pending approvals (the human
should re-confirm against the current state of the world).

Retry validation enforces:
- Identical action / symbol / side / type / volume / ticket
- Price drift within max(0.5%, deviation_points * symbol.point)
- Preview not expired
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ulid import ULID

from mt5_mcp.errors import invalid_approval_error
from mt5_mcp.types import ApprovalPreview, ErrorDetail


def new_request_id() -> str:
    """Mint a ULID — 128-bit, time-ordered, 26-char Crockford base32."""
    return str(ULID())


class ApprovalStore:
    """In-memory single-use store for pending ApprovalPreviews."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._previews: dict[str, ApprovalPreview] = {}

    def put(self, preview: ApprovalPreview) -> None:
        with self._lock:
            self._previews[preview.request_id] = preview

    def pop(self, request_id: str) -> ApprovalPreview | None:
        """Remove and return the preview if it exists and is un-expired."""
        with self._lock:
            preview = self._previews.pop(request_id, None)
        if preview is None:
            return None
        if preview.expires_at <= datetime.now(timezone.utc):
            return None
        return preview


def validate_retry(
    request: Any,                       # OrderRequest / ModifyOrderRequest / ClosePositionRequest
    *,
    preview: ApprovalPreview,
    current_price: Decimal,
    point: Decimal,
) -> ErrorDetail | None:
    """Check that `request` matches the stored `preview` within tolerances.

    Returns an ErrorDetail on mismatch, None on success. The caller is
    expected to have already retrieved `preview` via ApprovalStore.pop().
    """
    if preview.expires_at <= datetime.now(timezone.utc):
        return invalid_approval_error(reason="approval expired before retry arrived")

    echo = preview.request_echo

    # Identical fields. Each request type contributes a different subset.
    for field in ("symbol", "side", "type", "volume", "ticket"):
        if not hasattr(request, field):
            continue
        new_val = getattr(request, field)
        old_val = echo.get(field)
        if old_val is None:
            continue  # field not part of this preview's snapshot
        # Decimal-aware comparison: stored as JSON string in echo.
        if isinstance(new_val, Decimal):
            try:
                old_dec = Decimal(str(old_val))
            except Exception:
                return invalid_approval_error(
                    reason=f"{field} stored as non-numeric in preview"
                )
            if new_val != old_dec:
                return invalid_approval_error(
                    reason=f"{field} mismatch: preview={old_val} retry={new_val}"
                )
        elif new_val != old_val:
            return invalid_approval_error(
                reason=f"{field} mismatch: preview={old_val} retry={new_val}"
            )

    # Price drift tolerance: max(0.5% of reference, deviation_points * point).
    ref_price = preview.reference_quote.ask if echo.get("side") == "buy" \
                else preview.reference_quote.bid
    pct_band = ref_price * Decimal("0.005")
    dev = int(echo.get("deviation", 0))
    dev_band = Decimal(dev) * point
    tolerance = max(pct_band, dev_band)

    if abs(current_price - ref_price) > tolerance:
        return invalid_approval_error(
            reason=(
                f"price drifted beyond tolerance: ref={ref_price} now={current_price} "
                f"tolerance={tolerance}"
            )
        )

    return None
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_policy_consent.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/policy/consent.py tests/test_policy_consent.py
git commit -m "feat(phase-2): add approval-preview store and retry validator"
```

---

## Task 10: Implement `policy/preflight.py` (hard limits)

**Wave 3 — parallel.** Depends on T2 (types) + T3 (errors) + T4 (config). Independent of T7/T8/T9.

**Files:**
- Create: `src/mt5_mcp/policy/preflight.py`
- Create: `tests/test_policy_preflight.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_policy_preflight.py`:

```python
"""check_preflight_limits — hard refusal layer (no approval can override)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from mt5_mcp.config import Config, PolicySection, SymbolsSection
from mt5_mcp.policy.preflight import PreflightInputs, check_preflight_limits
from mt5_mcp.types import (
    CancelOrderRequest, ClosePositionRequest, ModifyOrderRequest, OrderRequest,
)


def _config(*, max_notional="100000", max_realised_loss="500", max_daily_loss="2000",
            allow=None, deny=None) -> Config:
    return Config(
        policy=PolicySection(
            auto_approve_notional=Decimal("1000"),
            max_notional_per_trade=Decimal(max_notional),
            max_realised_loss_per_close=Decimal(max_realised_loss),
            max_daily_loss=Decimal(max_daily_loss),
        ),
        symbols=SymbolsSection(allowlist=allow or [], denylist=deny or []),
    )


def _inputs(*, notional="100", running_daily_pnl="0", realised_loss_on_close="0") -> PreflightInputs:
    return PreflightInputs(
        notional=Decimal(notional),
        running_daily_realised_pnl=Decimal(running_daily_pnl),
        estimated_realised_loss_on_close=Decimal(realised_loss_on_close),
    )


def test_under_all_limits_passes():
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits("place_order", req, _inputs(), _config())
    assert err is None


def test_blocks_when_notional_above_max_per_trade():
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("1.0"))
    err = check_preflight_limits(
        "place_order", req, _inputs(notional="150000"),
        _config(max_notional="100000"),
    )
    assert err is not None
    assert err.code == "EXCEEDS_LOCAL_LIMIT"
    assert err.details["limit_name"] == "max_notional_per_trade"


def test_blocks_when_symbol_in_denylist():
    req = OrderRequest(symbol="XAUUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req, _inputs(),
        _config(deny=["XAUUSD"]),
    )
    assert err is not None
    assert err.details["limit_name"] == "denylist"


def test_blocks_when_allowlist_set_and_symbol_missing():
    req = OrderRequest(symbol="GBPJPY", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req, _inputs(),
        _config(allow=["EURUSD", "USDJPY"]),
    )
    assert err is not None
    assert err.details["limit_name"] == "allowlist"


def test_blocks_when_running_daily_loss_would_breach_threshold():
    # Daily loss limit is the absolute number; current loss is 1900, configured 2000.
    # A new order risks pushing past 2000. Pre-flight here errs on the conservative
    # side: refuse the new order if running daily loss already ≥ -max_daily_loss
    # OR projected loss would breach. We model the running loss as already-near-cap.
    req = OrderRequest(symbol="EURUSD", side="buy", type="market", volume=Decimal("0.1"))
    err = check_preflight_limits(
        "place_order", req,
        _inputs(running_daily_pnl="-1950"),
        _config(max_daily_loss="2000"),
    )
    assert err is not None
    assert err.details["limit_name"] == "max_daily_loss"


def test_close_position_blocks_when_realised_loss_above_per_close_cap():
    req = ClosePositionRequest(ticket=42)
    err = check_preflight_limits(
        "close_position", req,
        _inputs(realised_loss_on_close="-750"),
        _config(max_realised_loss="500"),
    )
    assert err is not None
    assert err.details["limit_name"] == "max_realised_loss_per_close"


def test_cancel_order_skips_all_checks():
    # cancel_order reduces exposure — preflight is a no-op even with denylist set.
    req = CancelOrderRequest(ticket=42)
    err = check_preflight_limits(
        "cancel_order", req, _inputs(notional="0"),
        _config(deny=["EURUSD"]),
    )
    assert err is None


def test_modify_order_does_not_use_max_notional_per_trade():
    # modify_order edits an existing position/order; we don't refuse on
    # notional cap (the original order's notional already passed it).
    # Allowlist still applies — but tests cover that under place_order.
    req = ModifyOrderRequest(ticket=42)
    err = check_preflight_limits(
        "modify_order", req, _inputs(notional="999999"),
        _config(max_notional="1000"),
    )
    assert err is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_policy_preflight.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/mt5_mcp/policy/preflight.py`**

```python
"""Pre-flight limit checks. UX optimisation, not a security control —
the broker's MT5 server enforces the real boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from mt5_mcp.config import Config
from mt5_mcp.errors import exceeds_local_limit_error
from mt5_mcp.types import ErrorDetail


@dataclass
class PreflightInputs:
    """Per-call snapshot the engine passes in.

    `notional` is the resolved notional in account currency for the
    request being attempted (computed by the tool from volume × ref-price).
    `running_daily_realised_pnl` is the day-to-date P&L sum (negative when
    losing). `estimated_realised_loss_on_close` is populated for
    close_position requests; the engine uses it to compare against
    `max_realised_loss_per_close` (also negative when realising a loss).
    """

    notional: Decimal
    running_daily_realised_pnl: Decimal = Decimal("0")
    estimated_realised_loss_on_close: Decimal = Decimal("0")


Action = Literal["place_order", "modify_order", "cancel_order", "close_position"]


def check_preflight_limits(
    action: Action,
    request: Any,
    inputs: PreflightInputs,
    config: Config,
) -> ErrorDetail | None:
    """Return an EXCEEDS_LOCAL_LIMIT ErrorDetail on refusal, None otherwise."""
    if action == "cancel_order":
        return None  # cancels reduce exposure; never refused locally

    symbol = getattr(request, "symbol", None)

    # Symbol allow/denylist (skip when symbol is unknown — modify/close use ticket).
    if symbol is not None:
        if symbol in config.symbols.denylist:
            return exceeds_local_limit_error(
                limit_name="denylist", configured=",".join(config.symbols.denylist),
                attempted=symbol,
            )
        if config.symbols.allowlist and symbol not in config.symbols.allowlist:
            return exceeds_local_limit_error(
                limit_name="allowlist", configured=",".join(config.symbols.allowlist),
                attempted=symbol,
            )

    # max_notional_per_trade — applies only to actions that ADD exposure
    # (place_order). close_position reduces exposure; modify_order edits an
    # existing position whose notional already passed at place time.
    if action == "place_order" and config.policy.max_notional_per_trade > 0:
        if inputs.notional > config.policy.max_notional_per_trade:
            return exceeds_local_limit_error(
                limit_name="max_notional_per_trade",
                configured=config.policy.max_notional_per_trade,
                attempted=inputs.notional,
            )

    # Daily loss cap — applies to place_order only. Realised P&L is negative
    # when losing; we compare absolute value against the configured cap.
    if action == "place_order" and config.policy.max_daily_loss > 0:
        loss_so_far = -inputs.running_daily_realised_pnl  # positive when losing
        if loss_so_far >= config.policy.max_daily_loss:
            return exceeds_local_limit_error(
                limit_name="max_daily_loss",
                configured=config.policy.max_daily_loss,
                attempted=loss_so_far,
            )

    # Realised-loss-on-close cap — close_position only.
    if action == "close_position" and config.policy.max_realised_loss_per_close > 0:
        loss_on_close = -inputs.estimated_realised_loss_on_close
        if loss_on_close > config.policy.max_realised_loss_per_close:
            return exceeds_local_limit_error(
                limit_name="max_realised_loss_per_close",
                configured=config.policy.max_realised_loss_per_close,
                attempted=loss_on_close,
            )

    return None
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_policy_preflight.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/policy/preflight.py tests/test_policy_preflight.py
git commit -m "feat(phase-2): add preflight limit checks"
```

---

## Task 11: Implement `policy/engine.py` (PolicyEngine + GuardedExecution)

**Wave 4 — sequential.** Depends on T7, T8, T9, T10 (all four submodules merged).

**Files:**
- Create: `src/mt5_mcp/policy/engine.py`
- Modify: `src/mt5_mcp/policy/__init__.py` (export `PolicyEngine`, `PreflightInputs`)
- Create: `tests/test_policy_engine.py`

- [ ] **Step 1: Update `policy/__init__.py` to export the engine**

```python
"""Policy engine: preflight + consent + idempotency + audit."""

from mt5_mcp.policy.engine import GuardedExecution, PolicyEngine
from mt5_mcp.policy.preflight import PreflightInputs

__all__ = ["GuardedExecution", "PolicyEngine", "PreflightInputs"]
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_policy_engine.py`:

```python
"""End-to-end coverage for the PolicyEngine context manager."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.config import Config, PolicySection
from mt5_mcp.policy import PolicyEngine, PreflightInputs
from mt5_mcp.policy.consent import ApprovalStore
from mt5_mcp.types import (
    ApprovalPreview, OrderRequest, OrderResult, Quote,
)
from tests.fakes import FakeOrderSendResult, TRADE_RETCODE_DONE


def _config(*, auto_approve="1000", max_notional="100000") -> Config:
    return Config(policy=PolicySection(
        auto_approve_notional=Decimal(auto_approve),
        max_notional_per_trade=Decimal(max_notional),
    ))


@pytest.fixture
def engine(tmp_path: Path) -> PolicyEngine:
    cfg = _config()
    e = PolicyEngine(
        config=cfg,
        idempotency_path=tmp_path / "idem.db",
        audit_path=tmp_path / "audit.jsonl",
    )
    yield e
    e.close()


def _raw_done(*, order: int, price: float = 1.0824) -> FakeOrderSendResult:
    return FakeOrderSendResult(retcode=TRADE_RETCODE_DONE, order=order,
                               volume=0.1, price=price)


def _raw_to_result(raw, *, action="place_order", symbol="EURUSD",
                   request_volume=Decimal("0.1"), request_echo=None) -> OrderResult:
    return OrderResult(
        success=raw.retcode == TRADE_RETCODE_DONE,
        ticket=raw.order if raw.order else None,
        action=action, symbol=symbol, volume=request_volume,
        price_filled=Decimal(str(raw.price)) if raw.price else None,
        request_echo=request_echo or {},
        replayed=False,
        error=None,
        server_response_code=raw.retcode,
    )


def test_under_threshold_executes_directly(engine: PolicyEngine, tmp_path):
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.1"))
    inputs = PreflightInputs(notional=Decimal("100"))
    with engine.guard("place_order", req,
                      requires_approval=False, preflight_inputs=inputs) as g:
        assert g.short_circuit is None
        raw = g.execute(lambda: _raw_done(order=42))
        out = g.finalize(_raw_to_result, request_echo={"symbol": "EURUSD"})

    assert out["success"] is True
    assert out["ticket"] == 42

    # Audit line written for executed.
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["action"] == "executed"
    assert rec["tool"] == "place_order"


def test_requires_approval_short_circuits_with_preview(engine: PolicyEngine, tmp_path):
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"))
    inputs = PreflightInputs(notional=Decimal("54000"))
    preview = ApprovalPreview(
        request_id="will-be-overwritten",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        summary="x", action="place_order", symbol="EURUSD",
        notional=Decimal("54000"), estimated_margin=Decimal("540"),
        reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                              ask=Decimal("1.0824"),
                              time=datetime.now(timezone.utc)),
        request_echo={"symbol": "EURUSD", "side": "buy", "volume": "0.5",
                      "type": "market", "deviation": 10},
    )

    with engine.guard("place_order", req,
                      requires_approval=True,
                      preview_factory=lambda: preview,
                      preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        out = g.short_circuit

    # Engine should have minted a real ULID and stored the preview.
    assert out["request_id"] != "will-be-overwritten"
    assert len(out["request_id"]) == 26

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["action"] == "requires_approval"


def test_approval_confirmed_executes_when_retry_matches(tmp_path: Path):
    cfg = _config()
    e = PolicyEngine(config=cfg, idempotency_path=tmp_path / "idem.db",
                     audit_path=tmp_path / "audit.jsonl")
    try:
        # First, get a preview.
        req1 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("0.5"), deviation=10)
        preview = ApprovalPreview(
            request_id="x",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            summary="x", action="place_order", symbol="EURUSD",
            notional=Decimal("54000"), estimated_margin=Decimal("540"),
            reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                                  ask=Decimal("1.0824"),
                                  time=datetime.now(timezone.utc)),
            request_echo={"symbol": "EURUSD", "side": "buy", "volume": "0.5",
                          "type": "market", "deviation": 10},
        )
        with e.guard("place_order", req1,
                     requires_approval=True,
                     preview_factory=lambda: preview,
                     preflight_inputs=PreflightInputs(notional=Decimal("54000"))) as g:
            request_id = g.short_circuit["request_id"]

        # Now retry with approval_confirmed=True and the same fields.
        req2 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("0.5"), deviation=10,
                            approval_confirmed=True,
                            approval_request_id=request_id)
        with e.guard("place_order", req2,
                     requires_approval=True,
                     current_price=Decimal("1.0824"),
                     symbol_point=Decimal("0.00001"),
                     preflight_inputs=PreflightInputs(notional=Decimal("54000"))) as g:
            assert g.short_circuit is None  # approved!
            raw = g.execute(lambda: _raw_done(order=99))
            out = g.finalize(_raw_to_result, request_echo={"symbol": "EURUSD"})
        assert out["success"] is True and out["ticket"] == 99
    finally:
        e.close()


def test_approval_invalid_when_volume_changes_between_calls(tmp_path: Path):
    cfg = _config()
    e = PolicyEngine(config=cfg, idempotency_path=tmp_path / "idem.db",
                     audit_path=tmp_path / "audit.jsonl")
    try:
        req1 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("0.5"))
        preview = ApprovalPreview(
            request_id="x",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            summary="x", action="place_order", symbol="EURUSD",
            notional=Decimal("54000"), estimated_margin=Decimal("540"),
            reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                                  ask=Decimal("1.0824"),
                                  time=datetime.now(timezone.utc)),
            request_echo={"symbol": "EURUSD", "side": "buy", "volume": "0.5",
                          "type": "market", "deviation": 10},
        )
        with e.guard("place_order", req1, requires_approval=True,
                     preview_factory=lambda: preview,
                     preflight_inputs=PreflightInputs(notional=Decimal("54000"))) as g:
            request_id = g.short_circuit["request_id"]

        # Different volume in the retry.
        req2 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("1.0"),  # ← changed
                            approval_confirmed=True, approval_request_id=request_id)
        with e.guard("place_order", req2, requires_approval=True,
                     current_price=Decimal("1.0824"),
                     symbol_point=Decimal("0.00001"),
                     preflight_inputs=PreflightInputs(notional=Decimal("108000"))) as g:
            assert g.short_circuit is not None
            assert g.short_circuit["error"]["code"] == "INVALID_APPROVAL"
    finally:
        e.close()


def test_preflight_refusal_short_circuits(engine: PolicyEngine, tmp_path):
    e = engine
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("100"))
    inputs = PreflightInputs(notional=Decimal("999999"))
    # Override config to a tight cap.
    e._config = _config(max_notional="1000")
    with e.guard("place_order", req, requires_approval=False,
                 preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        assert g.short_circuit["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"

    last = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert last["action"] == "preflight_refused"


def test_idempotency_replay_returns_cached_with_replayed_flag(engine: PolicyEngine):
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.1"), idempotency_key="k1")
    inputs = PreflightInputs(notional=Decimal("100"))
    with engine.guard("place_order", req, requires_approval=False,
                      preflight_inputs=inputs) as g:
        g.execute(lambda: _raw_done(order=77))
        first = g.finalize(_raw_to_result, request_echo={"x": 1})
    assert first["replayed"] is False

    # Same key, same hash → replay.
    with engine.guard("place_order", req, requires_approval=False,
                      preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        assert g.short_circuit["replayed"] is True
        assert g.short_circuit["ticket"] == 77


def test_idempotency_diverged_when_same_key_different_request(engine: PolicyEngine):
    req1 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                        volume=Decimal("0.1"), idempotency_key="k2")
    req2 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                        volume=Decimal("0.5"),  # different
                        idempotency_key="k2")
    inputs = PreflightInputs(notional=Decimal("100"))
    with engine.guard("place_order", req1, requires_approval=False,
                      preflight_inputs=inputs) as g:
        g.execute(lambda: _raw_done(order=88))
        g.finalize(_raw_to_result, request_echo={"x": 1})

    with engine.guard("place_order", req2, requires_approval=False,
                      preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        assert g.short_circuit["error"]["code"] == "IDEMPOTENCY_DIVERGED"
```

- [ ] **Step 3: Run tests — expect failure**

Run: `py -m pytest tests/test_policy_engine.py -v`
Expected: ImportError on `mt5_mcp.policy.engine`.

- [ ] **Step 4: Implement `src/mt5_mcp/policy/engine.py`**

```python
"""PolicyEngine — single facade over preflight + consent + idempotency + audit.

Tools call `with engine.guard(action, request, requires_approval=..., ...)`
inside their body, after they've computed the gate logic. The engine
handles the retry mechanism: storing previews, validating retries, caching
idempotent results, and writing the audit trail.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from pydantic import BaseModel

from mt5_mcp.config import Config
from mt5_mcp.errors import idempotency_diverged_error
from mt5_mcp.policy.audit import AuditLog
from mt5_mcp.policy.consent import ApprovalStore, new_request_id, validate_retry
from mt5_mcp.policy.idempotency import IdempotencyStore
from mt5_mcp.policy.preflight import PreflightInputs, check_preflight_limits
from mt5_mcp.types import ApprovalPreview, ErrorDetail, OrderResult


logger = logging.getLogger(__name__)


Action = Literal["place_order", "modify_order", "cancel_order", "close_position"]


@dataclass
class GuardedExecution:
    """Yielded by PolicyEngine.guard(); collaborates with the tool body."""

    action: Action
    request: BaseModel
    request_hash: str
    short_circuit: dict[str, Any] | None = None
    _finalized: bool = False
    _execute_started_at: float | None = None
    _execute_duration_ms: int | None = None
    _engine: "PolicyEngine | None" = None

    def execute(self, callback: Callable[[], Any]) -> Any:
        """Run the mt5 RPC; record duration. Re-raises on exception."""
        self._execute_started_at = time.perf_counter()
        try:
            return callback()
        finally:
            self._execute_duration_ms = int(
                (time.perf_counter() - self._execute_started_at) * 1000
            )

    def finalize(
        self,
        raw_to_result_fn: Callable[..., OrderResult],
        *,
        request_echo: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convert raw mt5 response → OrderResult; audit; cache; return JSON dict."""
        if self._engine is None:
            raise RuntimeError("GuardedExecution.finalize called without engine binding")
        return self._engine._finalize(self, raw_to_result_fn,
                                       request_echo=request_echo, **kwargs)


class PolicyEngine:
    def __init__(
        self,
        *,
        config: Config,
        idempotency_path: Path | str,
        audit_path: Path | str,
    ) -> None:
        self._config = config
        self._idempotency = IdempotencyStore(
            path=idempotency_path,
            ttl_seconds=config.idempotency.ttl_seconds,
        )
        self._audit = AuditLog(path=audit_path, max_bytes=config.audit.max_bytes)
        self._approvals = ApprovalStore()

    # --- public API -----------------------------------------------------

    @contextlib.contextmanager
    def guard(
        self,
        action: Action,
        request: BaseModel,
        *,
        requires_approval: bool,
        preview_factory: Callable[[], ApprovalPreview] | None = None,
        preflight_inputs: PreflightInputs | None = None,
        # When approval_confirmed=True and retry validation needs a fresh
        # price, the tool passes them in:
        current_price: Decimal | None = None,
        symbol_point: Decimal | None = None,
    ) -> Iterator[GuardedExecution]:
        request_hash = self._hash_request(request)
        g = GuardedExecution(action=action, request=request,
                             request_hash=request_hash, _engine=self)

        # 1. Idempotency lookup.
        idem_key = getattr(request, "idempotency_key", None)
        idem = self._idempotency.lookup(
            key=idem_key, action=action, request_hash=request_hash
        )
        if idem is not None:
            kind, payload = idem
            if kind == "hit":
                cached = json.loads(payload)
                cached["replayed"] = True
                self._audit.write({"tool": action, "action": "replay",
                                   "idempotency_key": idem_key,
                                   "request_hash": request_hash})
                g.short_circuit = cached
                yield g
                return
            if kind == "diverged":
                err = idempotency_diverged_error(key=str(idem_key), action=action)
                self._audit.write({"tool": action, "action": "idempotency_diverged",
                                   "idempotency_key": idem_key,
                                   "request_hash": request_hash})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

        # 2. Preflight checks.
        if preflight_inputs is not None:
            err = check_preflight_limits(action, request, preflight_inputs, self._config)
            if err is not None:
                self._audit.write({"tool": action, "action": "preflight_refused",
                                   "request_hash": request_hash,
                                   "limit_name": err.details.get("limit_name") if err.details else None})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

        # 3. Consent gate.
        if requires_approval:
            approval_confirmed = bool(getattr(request, "approval_confirmed", False))
            request_id = getattr(request, "approval_request_id", None)

            if not approval_confirmed:
                if preview_factory is None:
                    raise RuntimeError(
                        "guard(requires_approval=True) needs preview_factory"
                    )
                preview = preview_factory()
                # Engine mints the canonical ULID; tool's preview_factory may
                # have used a placeholder — overwrite for safety.
                preview = preview.model_copy(update={"request_id": new_request_id()})
                self._approvals.put(preview)
                self._audit.write({"tool": action, "action": "requires_approval",
                                   "request_id": preview.request_id,
                                   "request_hash": request_hash})
                g.short_circuit = preview.model_dump(mode="json")
                yield g
                return

            # approval_confirmed=True path.
            if not request_id:
                err = ErrorDetail(code="INVALID_APPROVAL",
                                   message="approval_confirmed=true requires approval_request_id",
                                   retryable=True, requires_human=True,
                                   details={"reason": "missing approval_request_id"})
                self._audit.write({"tool": action, "action": "invalid_approval",
                                   "request_hash": request_hash})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

            stored = self._approvals.pop(request_id)
            if stored is None:
                from mt5_mcp.errors import invalid_approval_error
                err = invalid_approval_error(reason="unknown or expired approval_request_id")
                self._audit.write({"tool": action, "action": "invalid_approval",
                                   "request_id": request_id,
                                   "request_hash": request_hash})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

            if current_price is None or symbol_point is None:
                raise RuntimeError(
                    "guard(approval_confirmed=true) needs current_price + symbol_point"
                )
            err = validate_retry(request, preview=stored,
                                  current_price=current_price, point=symbol_point)
            if err is not None:
                self._audit.write({"tool": action, "action": "invalid_approval",
                                   "request_id": request_id,
                                   "request_hash": request_hash,
                                   "reason": err.details.get("reason") if err.details else None})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return
            # Approval matched — fall through to execute.

        # 4. Yield to the tool body for execute() + finalize().
        try:
            yield g
        except Exception as exc:
            if not g._finalized:
                self._audit.write({"tool": action, "action": "error",
                                   "request_hash": request_hash,
                                   "exception_type": type(exc).__name__})
            raise

    def close(self) -> None:
        self._idempotency.close()
        self._audit.close()

    # --- helpers used by GuardedExecution.finalize ----------------------

    def _finalize(
        self,
        g: GuardedExecution,
        raw_to_result_fn: Callable[..., OrderResult],
        *,
        request_echo: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        # The tool body returned a raw mt5 response from execute(); we don't
        # have it here. The pattern is: tool stores raw, calls finalize and
        # passes raw_to_result_fn that closes over it. This API takes a
        # different tack — we expect the tool to call:
        #
        #   raw = g.execute(lambda: ...)
        #   return g.finalize(lambda: order_result_from_mt5_response(raw, ...))
        #
        # i.e. raw_to_result_fn here is a no-arg producer of OrderResult.
        result = raw_to_result_fn()
        result_dict = result.model_dump(mode="json")
        self._audit.write({
            "tool": g.action, "action": "executed",
            "request_hash": g.request_hash,
            "ticket": result.ticket,
            "duration_ms": g._execute_duration_ms,
            "result_status": "filled" if result.success else "rejected",
        })
        idem_key = getattr(g.request, "idempotency_key", None)
        if idem_key:
            self._idempotency.put(
                key=idem_key, action=g.action,
                request_hash=g.request_hash,
                result_json=json.dumps(result_dict, separators=(",", ":")),
            )
        g._finalized = True
        return result_dict

    # --- canonical hashing ----------------------------------------------

    @staticmethod
    def _hash_request(request: BaseModel) -> str:
        """SHA256 over canonical JSON, excluding approval_* fields."""
        data = request.model_dump(mode="json",
                                   exclude={"approval_confirmed", "approval_request_id"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**Important correction to the public API:** the test `test_under_threshold_executes_directly` calls `g.finalize(_raw_to_result, request_echo={...})` where `_raw_to_result` takes the raw object. To match, the engine's `_finalize` must accept the raw and the conversion function. Update `GuardedExecution.execute` to stash the raw, and `_finalize` to call the function with it:

Replace `GuardedExecution.execute` and `_finalize`:

```python
@dataclass
class GuardedExecution:
    action: Action
    request: BaseModel
    request_hash: str
    short_circuit: dict[str, Any] | None = None
    _finalized: bool = False
    _raw: Any = None
    _execute_duration_ms: int | None = None
    _engine: "PolicyEngine | None" = None

    def execute(self, callback: Callable[[], Any]) -> Any:
        t0 = time.perf_counter()
        try:
            self._raw = callback()
            return self._raw
        finally:
            self._execute_duration_ms = int((time.perf_counter() - t0) * 1000)

    def finalize(
        self,
        raw_to_result_fn: Callable[..., OrderResult],
        *,
        request_echo: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._engine is None:
            raise RuntimeError("GuardedExecution.finalize called without engine binding")
        return self._engine._finalize(
            self, raw_to_result_fn, request_echo=request_echo, **kwargs
        )
```

And `PolicyEngine._finalize`:

```python
def _finalize(self, g: GuardedExecution, raw_to_result_fn, *, request_echo, **kwargs):
    result = raw_to_result_fn(
        g._raw,
        request_echo=request_echo,
        **{k: v for k, v in kwargs.items()},
    )
    if not isinstance(result, OrderResult):
        raise TypeError("raw_to_result_fn must return an OrderResult")
    result_dict = result.model_dump(mode="json")
    self._audit.write({
        "tool": g.action, "action": "executed",
        "request_hash": g.request_hash,
        "ticket": result.ticket,
        "duration_ms": g._execute_duration_ms,
        "result_status": "filled" if result.success else "rejected",
    })
    idem_key = getattr(g.request, "idempotency_key", None)
    if idem_key:
        self._idempotency.put(
            key=idem_key, action=g.action,
            request_hash=g.request_hash,
            result_json=json.dumps(result_dict, separators=(",", ":")),
        )
    g._finalized = True
    return result_dict
```

The engine now invokes `raw_to_result_fn(raw, request_echo=..., **kwargs)`. The test fixture's `_raw_to_result` matches this signature.

- [ ] **Step 5: Update test signatures**

Adjust the engine fixture and the tests so `_raw_to_result` is invoked with `(raw, *, request_echo, ...)`. The test definitions above already match — re-read them.

- [ ] **Step 6: Run tests — expect pass**

Run: `py -m pytest tests/test_policy_engine.py -v`
Expected: 7 tests pass.

- [ ] **Step 7: Run the full suite**

Run: `py -m pytest -q`
Expected: all green; counts grow by however many tests this task added (+ submodule tests from earlier waves).

- [ ] **Step 8: Commit**

```bash
git add src/mt5_mcp/policy/__init__.py src/mt5_mcp/policy/engine.py tests/test_policy_engine.py
git commit -m "feat(phase-2): assemble PolicyEngine with guard() context manager"
```

---

## Task 12: Wire `PolicyEngine` into `AppContext`

**Wave 5 — sequential.** Depends on T11 (engine) + T4 (config) + T5 (fakes).

**Files:**
- Modify: `src/mt5_mcp/server.py`
- Modify: `tests/conftest.py` (extend `_reset_app_context` to close the engine)
- Modify: `tests/test_server_bootstrap.py`

- [ ] **Step 1: Write a failing test that exercises the new field**

Append to `tests/test_server_bootstrap.py`:

```python
def test_app_context_includes_policy_engine(tmp_path):
    """build_context() instantiates a PolicyEngine wired to per-OS paths."""
    from mt5_mcp.config import Config, IdempotencySection, AuditSection
    from mt5_mcp.policy import PolicyEngine
    from mt5_mcp.server import build_context, reset_context_for_tests
    from tests.fakes import FakeMT5

    reset_context_for_tests()
    # Use tmp_path overrides so we don't pollute the real ~/.local/share/mt5-mcp.
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'[idempotency]\n'
        f'path = "{(tmp_path / "idem.db").as_posix()}"\n\n'
        f'[audit]\n'
        f'path = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    ctx = build_context(config_path=cfg_file, mt5_module=FakeMT5())
    try:
        assert isinstance(ctx.policy, PolicyEngine)
    finally:
        reset_context_for_tests()
```

- [ ] **Step 2: Run test — expect failure (`AppContext` has no `policy` field)**

Run: `py -m pytest tests/test_server_bootstrap.py::test_app_context_includes_policy_engine -v`
Expected: AttributeError or AssertionError on `ctx.policy`.

- [ ] **Step 3: Update `src/mt5_mcp/server.py`**

Replace the `AppContext` definition and the `build_context()` body:

```python
@dataclass
class AppContext:
    """Hands-off wiring passed from the server to each tool module."""

    client: MT5Client
    symbols: SymbolPrep
    config_watcher: ConfigWatcher | None
    policy: PolicyEngine

    @property
    def config(self) -> Config:
        if self.config_watcher is not None:
            return self.config_watcher.current
        return Config()
```

Add the import at the top of `server.py`:

```python
from mt5_mcp.policy import PolicyEngine
```

Update `build_context()` to construct the engine:

```python
def build_context(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> AppContext:
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            return _ctx
        watcher: ConfigWatcher | None = None
        path = config_path or default_config_path()
        if path.exists():
            watcher = ConfigWatcher(path)
            watcher.start()
            cfg = watcher.current
        else:
            cfg = load_config()
        client = MT5Client(
            terminal_path=cfg.mt5.terminal_path or None,
            mt5_module=mt5_module,
        )
        symbols = SymbolPrep(client)
        policy = PolicyEngine(
            config=cfg,
            idempotency_path=cfg.idempotency.path,
            audit_path=cfg.audit.path,
        )
        _ctx = AppContext(client=client, symbols=symbols,
                          config_watcher=watcher, policy=policy)
        return _ctx
```

Update `reset_context_for_tests()` to close the engine:

```python
def reset_context_for_tests() -> None:
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            if _ctx.config_watcher is not None:
                _ctx.config_watcher.stop()
            _ctx.policy.close()
        _ctx = None
```

- [ ] **Step 4: Update `tests/conftest.py`**

The autouse fixture is already calling `reset_context_for_tests()` — no change needed since it already wraps both ends. Verify:

```python
@pytest.fixture(autouse=True)
def _reset_app_context():
    from mt5_mcp.server import reset_context_for_tests
    reset_context_for_tests()
    yield
    reset_context_for_tests()
```

- [ ] **Step 5: Update existing fixtures that build a server**

Phase-1 test fixtures (e.g. `test_tools_account.py::server_and_mt5`) call `build_server(mt5_module=fake)` which calls `build_context()` with no config path. Today this resolves to the OS-default config path; if that file doesn't exist, defaults are used — including the `platformdirs` user-data path for the SQLite DB and JSONL log.

That's a problem in tests: they'd write to the real `~/.local/share/mt5-mcp/` (or `%LOCALAPPDATA%`).

Fix: introduce a `tmp_path` override in the fixture by writing a minimal config file. Update each `server_and_mt5` fixture in `test_tools_*.py` to take `tmp_path` and pass `config_path`:

```python
@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\n'
        f'path = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\n'
        f'path = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, fake
```

Apply this change to: `tests/test_tools_account.py`, `tests/test_tools_market.py`, `tests/test_tools_orders.py`, `tests/test_tools_positions.py`, `tests/test_tools_history.py`, `tests/test_tools_system.py`, `tests/test_cli_doctor.py`, `tests/test_cli_export_symbols.py`, `tests/test_server_bootstrap.py` — wherever `build_server(mt5_module=...)` is called.

- [ ] **Step 6: Run the full suite**

Run: `py -m pytest -q`
Expected: all green. New count: 91 + new tests across this wave.

- [ ] **Step 7: Commit**

```bash
git add src/mt5_mcp/server.py tests/test_server_bootstrap.py tests/test_tools_account.py tests/test_tools_market.py tests/test_tools_orders.py tests/test_tools_positions.py tests/test_tools_history.py tests/test_tools_system.py tests/test_cli_doctor.py tests/test_cli_export_symbols.py
git commit -m "feat(phase-2): instantiate PolicyEngine in AppContext"
```

---

## Task 13: Implement `place_order` tool

**Wave 6 — parallel with T14.** Depends on T12 (engine wired into AppContext) + T6 (conversions).

**Files:**
- Modify: `src/mt5_mcp/tools/orders.py`
- Create: `tests/test_tools_place_order.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_place_order.py`:

```python
"""End-to-end coverage for place_order — the canonical Phase-2 tool flow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrderSendResult, FakeSymbolInfo, FakeTerminalInfo,
    FakeTick, TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo(currency="USD", leverage=100)
    info = FakeSymbolInfo(name="EURUSD", visible=True)
    fake._symbol_info = {"EURUSD": info}
    fake._symbol_info_tick = {
        "EURUSD": FakeTick(time=int(datetime(2026, 4, 21, 13, 0,
                                              tzinfo=timezone.utc).timestamp()),
                           bid=1.0823, ask=1.0824)
    }
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=12345, deal=99,
                                            volume=0.10, price=1.0824)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\n'
        'auto_approve_notional = "1000"\n'
        'max_notional_per_trade = "100000"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_small_notional_executes_directly(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="0.10")
    assert out["success"] is True
    assert out["ticket"] == 12345
    assert out["replayed"] is False
    # mt5.order_send was called once.
    assert len(fake.order_send_calls) == 1
    sent = fake.order_send_calls[0]
    assert sent["symbol"] == "EURUSD"
    assert sent["volume"] == 0.10
    assert sent["type"] == fake.ORDER_TYPE_BUY
    assert sent["price"] == 1.0824


def test_above_threshold_returns_preview(server_and_mt5):
    server, fake = server_and_mt5
    # 0.10 lots * 100,000 contract size * 1.0824 price ≈ $10,824 — over $1000 threshold.
    # We'll bump contract_size implicitly by using volume=10 lots (~$1.08M).
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="10.0")
    # No order was sent.
    assert len(fake.order_send_calls) == 0
    assert out["action"] == "place_order"
    assert "request_id" in out
    assert "expires_at" in out
    assert "summary" in out
    assert out["notional"] == "10.824"  # 10.0 lots × 1.0824 price (volume × price)


def test_approval_confirmed_retry_executes(server_and_mt5):
    server, fake = server_and_mt5
    # Trigger preview.
    preview = _call(server, "place_order",
                    symbol="EURUSD", side="buy", type="market", volume="10.0")
    request_id = preview["request_id"]
    # Retry.
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="10.0",
                approval_confirmed=True, approval_request_id=request_id)
    assert out["success"] is True
    assert out["ticket"] == 12345


def test_above_max_notional_rejected_even_with_approval(server_and_mt5, tmp_path):
    """Pre-flight refusals are absolute — approval doesn't override."""
    # Reset fixture with a tighter cap.
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.0823, ask=1.0824)}
    cfg = tmp_path / "config2.toml"
    cfg.write_text(
        '[policy]\n'
        'auto_approve_notional = "0"\n'
        'max_notional_per_trade = "5"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = _call(server, "place_order",
                symbol="EURUSD", side="buy", type="market", volume="10.0",
                approval_confirmed=True, approval_request_id="01HX...")
    assert "error" in out
    assert out["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"
    assert out["error"]["details"]["limit_name"] == "max_notional_per_trade"
    assert len(fake.order_send_calls) == 0


def test_idempotency_replay_returns_cached_with_replayed_true(server_and_mt5):
    server, fake = server_and_mt5
    out1 = _call(server, "place_order",
                 symbol="EURUSD", side="buy", type="market", volume="0.10",
                 idempotency_key="k-once")
    assert out1["success"] is True and out1["replayed"] is False
    # Same key, same hash.
    out2 = _call(server, "place_order",
                 symbol="EURUSD", side="buy", type="market", volume="0.10",
                 idempotency_key="k-once")
    assert out2["replayed"] is True
    assert out2["ticket"] == 12345
    # Only one underlying order_send call across both attempts.
    assert len(fake.order_send_calls) == 1


def test_invalid_symbol_returns_symbol_not_found(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "place_order",
                symbol="UNKNOWN", side="buy", type="market", volume="0.10")
    assert "error" in out
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_tools_place_order.py -v`
Expected: tool not registered.

- [ ] **Step 3: Implement `place_order` in `src/mt5_mcp/tools/orders.py`**

Replace the file:

```python
"""Order tools: get_orders (read), place_order (mutating).

Phase 2 adds modify_order / cancel_order in subsequent tasks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import (
    epoch_to_utc, order_request_to_mt5_dict, order_result_from_mt5_response,
)
from mt5_mcp.errors import MT5Error
from mt5_mcp.policy.consent import new_request_id
from mt5_mcp.policy.preflight import PreflightInputs
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import (
    ApprovalPreview, Order, OrderRequest, Quote,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    @error_envelope
    def get_orders(symbol: str | None = None) -> list[Order]:
        """Pending orders, optionally filtered to a single symbol."""
        ctx = get_context()
        if symbol:
            raws = ctx.client.call(lambda m: m.orders_get(symbol=symbol))
        else:
            raws = ctx.client.call(lambda m: m.orders_get())
        if raws is None:
            return []
        from mt5_mcp.adapter.conversions import order_from_raw
        offset = ctx.client.broker_offset_minutes
        return [order_from_raw(r, broker_offset_minutes=offset) for r in raws]

    @mcp.tool()
    @error_envelope
    def place_order(
        symbol: str,
        side: str,
        type: str,
        volume: str,
        price: str | None = None,
        stop_limit_price: str | None = None,
        sl: str | None = None,
        tp: str | None = None,
        deviation: int = 10,
        comment: str | None = None,
        idempotency_key: str | None = None,
        approval_confirmed: bool = False,
        approval_request_id: str | None = None,
    ) -> dict:
        """Place a market or pending order. Optional SL / TP / deviation.

        Above `policy.auto_approve_notional`, returns an ApprovalPreview;
        retry with approval_confirmed=true and the same request fields to
        proceed. Pass `idempotency_key` (UUIDv4 recommended) to dedupe
        retries within `idempotency.ttl_seconds`.
        """
        ctx = get_context()
        req = OrderRequest(
            symbol=symbol, side=side, type=type, volume=Decimal(volume),
            price=Decimal(price) if price else None,
            stop_limit_price=Decimal(stop_limit_price) if stop_limit_price else None,
            sl=Decimal(sl) if sl else None,
            tp=Decimal(tp) if tp else None,
            deviation=deviation, comment=comment,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        # Adapter prep — raises MT5Error caught by error_envelope.
        info = ctx.symbols.get(symbol)
        ctx.symbols.validate_volume(symbol, req.volume)
        if req.price is not None:
            req = req.model_copy(update={
                "price": ctx.symbols.quantise_price(symbol, req.price)
            })
        filling = ctx.symbols.pick_filling_mode(symbol, order_type=req.type)

        # Resolve a reference price for notional + fill-price.
        if req.price is not None:
            ref_price = req.price
            tick = None
        else:
            tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
            if tick is None:
                from mt5_mcp.types import ErrorDetail
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_ENABLED",
                    message=f"No tick data for {symbol}; market may be closed.",
                    retryable=True, requires_human=False,
                    details={"symbol": symbol},
                ))
            ref_price = Decimal(str(tick.ask if req.side == "buy" else tick.bid))

        notional = req.volume * ref_price

        # Gate trigger — place_order uses notional vs. auto-approve threshold.
        cfg = ctx.config
        requires_approval = (
            cfg.policy.auto_approve_notional > 0
            and notional >= cfg.policy.auto_approve_notional
        )

        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        def build_preview() -> ApprovalPreview:
            t = tick or ctx.client.call(lambda m: m.symbol_info_tick(symbol))
            return ApprovalPreview(
                request_id=new_request_id(),  # engine overrides anyway
                expires_at=datetime.now(timezone.utc)
                          + timedelta(seconds=cfg.policy.approval_ttl_seconds),
                summary=(f"{req.side.upper()} {req.volume} {symbol} @ {req.type} "
                         f"(~{notional} {currency})"),
                action="place_order", symbol=symbol,
                notional=notional,
                estimated_margin=notional / leverage,
                reference_quote=Quote(
                    symbol=symbol,
                    bid=Decimal(str(t.bid)), ask=Decimal(str(t.ask)),
                    time=epoch_to_utc(t.time, ctx.client.broker_offset_minutes),
                ),
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
            )

        preflight = PreflightInputs(notional=notional)
        symbol_point = Decimal(str(getattr(info, "point", 0.00001)))

        with ctx.policy.guard(
            "place_order", req,
            requires_approval=requires_approval,
            preview_factory=build_preview if requires_approval else None,
            preflight_inputs=preflight,
            current_price=ref_price if approval_confirmed else None,
            symbol_point=symbol_point if approval_confirmed else None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5_dict = order_request_to_mt5_dict(
                req, symbol_info=info, filling_mode=filling,
                price=ref_price, mt5=ctx.client.mt5,
            )
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="place_order", symbol=symbol,
                request_volume=req.volume,
            )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_tools_place_order.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Run the full suite**

Run: `py -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/tools/orders.py tests/test_tools_place_order.py
git commit -m "feat(phase-2): add place_order tool with full policy pipeline"
```

---

## Task 14: Implement `close_position` tool

**Wave 6 — parallel with T13.** Depends on T12 + T6. Different file from T13.

**Files:**
- Modify: `src/mt5_mcp/tools/positions.py`
- Create: `tests/test_tools_close_position.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_close_position.py`:

```python
"""close_position end-to-end."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrderSendResult, FakePosition, FakeSymbolInfo,
    FakeTerminalInfo, FakeTick, POSITION_TYPE_BUY, TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.0823, ask=1.0824)}
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=0.5, price_open=1.0800, price_current=1.0824,
                     profit=12.0),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=42, deal=999,
                                            volume=0.5, price=1.0823)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\n'
        'auto_approve_notional = "1000000"\n'  # don't gate small closes
        'max_realised_loss_per_close = "100"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_close_in_full(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "close_position", ticket=42)
    assert out["success"] is True
    assert out["ticket"] == 42
    assert len(fake.order_send_calls) == 1
    sent = fake.order_send_calls[0]
    assert sent["volume"] == 0.5
    # A buy position is closed by sending a SELL deal.
    assert sent["type"] == fake.ORDER_TYPE_SELL
    assert sent["position"] == 42  # mt5lib uses `position` for close_by_ticket


def test_close_partial_volume(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "close_position", ticket=42, volume="0.2")
    assert out["success"] is True
    assert fake.order_send_calls[0]["volume"] == 0.2


def test_close_unknown_ticket_returns_invalid_ticket(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = ()
    out = _call(server, "close_position", ticket=99999)
    assert "error" in out
    assert out["error"]["code"] == "INVALID_TICKET"


def test_close_blocked_by_max_realised_loss_per_close(tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.05, ask=1.0501)}
    # Buy at 1.10, current 1.05 → losing $5000 on 1 lot (1.10-1.05)*100k.
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=1.0, price_open=1.10, price_current=1.05,
                     profit=-5000.0),
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\n'
        'max_realised_loss_per_close = "100"\n'
        f'\n[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    out = _call(server, "close_position", ticket=42)
    assert "error" in out
    assert out["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"
    assert out["error"]["details"]["limit_name"] == "max_realised_loss_per_close"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_tools_close_position.py -v`
Expected: tool not registered.

- [ ] **Step 3: Implement `close_position` in `src/mt5_mcp/tools/positions.py`**

Replace the existing `register()` body and add the new tool:

```python
"""Position tools: get_positions (read), close_position (mutating)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import (
    epoch_to_utc, order_result_from_mt5_response, position_from_raw,
)
from mt5_mcp.errors import MT5Error, invalid_ticket_error
from mt5_mcp.policy.consent import new_request_id
from mt5_mcp.policy.preflight import PreflightInputs
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import (
    ApprovalPreview, ClosePositionRequest, ErrorDetail, Position, Quote,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    @error_envelope
    def get_positions(symbol: str | None = None) -> list[Position]:
        """Open positions, optionally filtered to a single symbol."""
        ctx = get_context()
        if symbol:
            raws = ctx.client.call(lambda m: m.positions_get(symbol=symbol))
        else:
            raws = ctx.client.call(lambda m: m.positions_get())
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [position_from_raw(r, broker_offset_minutes=offset) for r in raws]

    @mcp.tool()
    @error_envelope
    def close_position(
        ticket: int,
        volume: str | None = None,
        idempotency_key: str | None = None,
        approval_confirmed: bool = False,
        approval_request_id: str | None = None,
    ) -> dict:
        """Close an open position in full or part by ticket."""
        ctx = get_context()
        req = ClosePositionRequest(
            ticket=ticket,
            volume=Decimal(volume) if volume else None,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        positions = ctx.client.call(lambda m: m.positions_get(ticket=ticket))
        if not positions:
            raise MT5Error(invalid_ticket_error(ticket=ticket, kind="position"))
        pos = positions[0]
        symbol = pos.symbol
        info = ctx.symbols.get(symbol)
        close_volume = req.volume or Decimal(str(pos.volume))

        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_ENABLED",
                message=f"No tick data for {symbol}; market may be closed.",
                retryable=True, requires_human=False,
                details={"symbol": symbol},
            ))
        # Closing a BUY needs a SELL deal (and vice versa).
        from tests.fakes import POSITION_TYPE_BUY  # constant; safe via the live module too
        is_buy_position = pos.type == ctx.client.mt5.POSITION_TYPE_BUY
        close_price = Decimal(str(tick.bid if is_buy_position else tick.ask))
        notional = close_volume * close_price
        # Estimated realised loss on close (negative when losing).
        # ((close_price - open_price) * volume * sign), where buy:+, sell:-.
        sign = Decimal("1") if is_buy_position else Decimal("-1")
        realised = (close_price - Decimal(str(pos.price_open))) * close_volume * sign

        cfg = ctx.config
        requires_approval = (
            cfg.policy.auto_approve_notional > 0
            and notional >= cfg.policy.auto_approve_notional
        )
        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        def build_preview() -> ApprovalPreview:
            return ApprovalPreview(
                request_id=new_request_id(),
                expires_at=datetime.now(timezone.utc)
                          + timedelta(seconds=cfg.policy.approval_ttl_seconds),
                summary=(f"CLOSE {close_volume} {symbol} @ ~{close_price} "
                         f"(~{notional} {currency})"),
                action="close_position", symbol=symbol, notional=notional,
                estimated_margin=notional / leverage,
                reference_quote=Quote(
                    symbol=symbol,
                    bid=Decimal(str(tick.bid)), ask=Decimal(str(tick.ask)),
                    time=epoch_to_utc(tick.time, ctx.client.broker_offset_minutes),
                ),
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
            )

        preflight = PreflightInputs(
            notional=notional,
            estimated_realised_loss_on_close=realised,
        )
        symbol_point = Decimal(str(getattr(info, "point", 0.00001)))

        with ctx.policy.guard(
            "close_position", req,
            requires_approval=requires_approval,
            preview_factory=build_preview if requires_approval else None,
            preflight_inputs=preflight,
            current_price=close_price if approval_confirmed else None,
            symbol_point=symbol_point if approval_confirmed else None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5 = ctx.client.mt5
            mt5_dict = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(close_volume),
                "type": mt5.ORDER_TYPE_SELL if is_buy_position else mt5.ORDER_TYPE_BUY,
                "position": int(ticket),
                "price": float(close_price),
                "deviation": 10,
                "type_filling": ctx.symbols.pick_filling_mode(symbol, order_type="market"),
                "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
                "magic": 0,
            }
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="close_position", symbol=symbol,
                request_volume=close_volume,
            )
```

Remove the inline `from tests.fakes import POSITION_TYPE_BUY` — production code must NOT import from `tests.`. Use `ctx.client.mt5.POSITION_TYPE_BUY` (already shown) and delete the unused import.

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_tools_close_position.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/tools/positions.py tests/test_tools_close_position.py
git commit -m "feat(phase-2): add close_position tool"
```

---

## Task 15: Implement `modify_order` tool

**Wave 7 — sequential after T13** (same file: `tools/orders.py`).

**Files:**
- Modify: `src/mt5_mcp/tools/orders.py` (append to the `register()` body)
- Create: `tests/test_tools_modify_order.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_modify_order.py`:

```python
"""modify_order: covers pending-order edits AND position SL/TP changes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrder, FakeOrderSendResult, FakePosition,
    FakeSymbolInfo, FakeTerminalInfo, FakeTick, ORDER_TYPE_BUY_LIMIT,
    POSITION_TYPE_BUY, TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._symbol_info_tick = {"EURUSD": FakeTick(time=1, bid=1.0823, ask=1.0824)}
    fake._positions_get = (
        FakePosition(ticket=42, symbol="EURUSD", type=POSITION_TYPE_BUY,
                     volume=0.5, price_open=1.0800, price_current=1.0824,
                     sl=1.0750, tp=1.0900),
    )
    fake._orders_get = (
        FakeOrder(ticket=77, symbol="EURUSD", type=ORDER_TYPE_BUY_LIMIT,
                  price_open=1.0700, volume_initial=0.1, volume_current=0.1),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=42, deal=0,
                                            volume=0.5, price=1.0824)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\nauto_approve_notional = "1000000"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_tighten_sl_on_position_auto_approves(server_and_mt5):
    """Moving SL closer to current price (more protective) auto-approves."""
    server, fake = server_and_mt5
    # Position: buy @ 1.08, current 1.0824, old SL 1.0750. New SL 1.0790 is tighter.
    out = _call(server, "modify_order", ticket=42, sl="1.0790")
    assert out["success"] is True
    assert len(fake.order_send_calls) == 1
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_SLTP
    assert sent["sl"] == 1.0790


def test_widen_sl_on_position_requires_approval(server_and_mt5):
    """Moving SL further from current price (less protective) trips the gate."""
    server, fake = server_and_mt5
    # Old SL 1.0750. New SL 1.0700 is further from current (1.0824) → widening.
    out = _call(server, "modify_order", ticket=42, sl="1.0700")
    assert "request_id" in out
    assert out["action"] == "modify_order"
    assert len(fake.order_send_calls) == 0


def test_remove_sl_requires_approval(server_and_mt5):
    """Setting SL to None when previously set is the most permissive change."""
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=42, sl="0")  # 0 = remove in mt5lib semantics
    # Our heuristic treats "remove" as widening.
    assert "request_id" in out


def test_modify_pending_order_price(server_and_mt5):
    """Edit the limit price of a pending buy_limit order."""
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=77, price="1.0680")
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_MODIFY
    assert sent["order"] == 77
    assert sent["price"] == 1.0680


def test_modify_unknown_ticket(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "modify_order", ticket=99999, sl="1.07")
    assert out["error"]["code"] == "INVALID_TICKET"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_tools_modify_order.py -v`
Expected: tool not registered.

- [ ] **Step 3: Append `modify_order` to `src/mt5_mcp/tools/orders.py`**

Inside the existing `register()` function, after `place_order`:

```python
    @mcp.tool()
    @error_envelope
    def modify_order(
        ticket: int,
        sl: str | None = None,
        tp: str | None = None,
        price: str | None = None,
        expiration: str | None = None,
        idempotency_key: str | None = None,
        approval_confirmed: bool = False,
        approval_request_id: str | None = None,
    ) -> dict:
        """Modify SL/TP on a position or price/expiration on a pending order.

        Widening or removing an existing SL/TP requires approval; tightening
        auto-approves regardless of notional.
        """
        from datetime import datetime as _dt
        from mt5_mcp.types import ModifyOrderRequest
        from mt5_mcp.errors import invalid_ticket_error

        ctx = get_context()
        req = ModifyOrderRequest(
            ticket=ticket,
            sl=Decimal(sl) if sl is not None else None,
            tp=Decimal(tp) if tp is not None else None,
            price=Decimal(price) if price is not None else None,
            expiration=_dt.fromisoformat(expiration.replace("Z", "+00:00"))
                       if expiration else None,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        # Look up the position first; fall back to pending order.
        positions = ctx.client.call(lambda m: m.positions_get(ticket=ticket))
        orders = ctx.client.call(lambda m: m.orders_get(ticket=ticket))
        is_position = bool(positions)
        is_order = bool(orders) and not is_position
        if not is_position and not is_order:
            raise MT5Error(invalid_ticket_error(ticket=ticket, kind="order"))

        target = positions[0] if is_position else orders[0]
        symbol = target.symbol
        info = ctx.symbols.get(symbol)

        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        current_price = Decimal(str(tick.bid)) if tick else Decimal("0")

        # Gate logic: only when widening / removing SL or TP on a position.
        old_sl = Decimal(str(getattr(target, "sl", 0) or 0))
        old_tp = Decimal(str(getattr(target, "tp", 0) or 0))
        # Heuristic: a stop is "wider" if its distance from current_price grows,
        # OR if it goes from non-zero to zero (removed).
        def _is_widening(old: Decimal, new: Decimal | None) -> bool:
            if new is None:
                return False
            if old != 0 and new == 0:
                return True  # removal
            if old == 0:
                return False  # adding when none was set is tightening
            return abs(current_price - new) > abs(current_price - old)

        widening = (
            (req.sl is not None and _is_widening(old_sl, req.sl))
            or (req.tp is not None and _is_widening(old_tp, req.tp))
        )
        requires_approval = is_position and widening

        # Notional only used in the preview (modify_order doesn't preflight on it).
        volume = Decimal(str(getattr(target, "volume", getattr(target, "volume_current", 0))))
        notional = volume * current_price
        cfg = ctx.config
        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        def build_preview() -> ApprovalPreview:
            return ApprovalPreview(
                request_id=new_request_id(),
                expires_at=datetime.now(timezone.utc)
                          + timedelta(seconds=cfg.policy.approval_ttl_seconds),
                summary=(f"MODIFY ticket {ticket} {symbol} "
                         f"SL={req.sl} TP={req.tp} (~{notional} {currency})"),
                action="modify_order", symbol=symbol, notional=notional,
                estimated_margin=notional / leverage,
                reference_quote=Quote(
                    symbol=symbol,
                    bid=Decimal(str(tick.bid)), ask=Decimal(str(tick.ask)),
                    time=epoch_to_utc(tick.time, ctx.client.broker_offset_minutes),
                ),
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
            )

        symbol_point = Decimal(str(getattr(info, "point", 0.00001)))
        preflight = PreflightInputs(notional=notional)

        with ctx.policy.guard(
            "modify_order", req,
            requires_approval=requires_approval,
            preview_factory=build_preview if requires_approval else None,
            preflight_inputs=preflight,
            current_price=current_price if approval_confirmed else None,
            symbol_point=symbol_point if approval_confirmed else None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5 = ctx.client.mt5
            if is_position:
                mt5_dict = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": symbol,
                    "position": int(ticket),
                    "sl": float(req.sl) if req.sl is not None else float(old_sl),
                    "tp": float(req.tp) if req.tp is not None else float(old_tp),
                }
            else:
                mt5_dict = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": int(ticket),
                    "price": float(req.price) if req.price is not None else float(target.price_open),
                    "sl": float(req.sl) if req.sl is not None else 0.0,
                    "tp": float(req.tp) if req.tp is not None else 0.0,
                    "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
                }
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="modify_order", symbol=symbol,
                request_volume=volume,
            )
```

The `FakeMT5` needs `TRADE_ACTION_SLTP`, `TRADE_ACTION_MODIFY`, `TRADE_ACTION_DEAL`, `TRADE_ACTION_PENDING` exposed as constants. Add them in `tests/fakes.py` if not present:

```python
TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
```

And on `FakeMT5`:

```python
TRADE_ACTION_DEAL: int = TRADE_ACTION_DEAL
TRADE_ACTION_PENDING: int = TRADE_ACTION_PENDING
TRADE_ACTION_SLTP: int = TRADE_ACTION_SLTP
TRADE_ACTION_MODIFY: int = TRADE_ACTION_MODIFY
ORDER_TYPE_BUY: int = 0
ORDER_TYPE_SELL: int = 1
ORDER_TYPE_BUY_STOP_LIMIT: int = 6
ORDER_TYPE_SELL_STOP_LIMIT: int = 7
```

(Some of these are already in `FakeMT5` from Phase 1; add only what's missing.)

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_tools_modify_order.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/tools/orders.py tests/test_tools_modify_order.py tests/fakes.py
git commit -m "feat(phase-2): add modify_order tool with SL-widening gate"
```

---

## Task 16b: Implement `cancel_order` tool

**Wave 7 — sequential after T15** (same file).

**Files:**
- Modify: `src/mt5_mcp/tools/orders.py` (append to `register()` body)
- Create: `tests/test_tools_cancel_order.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools_cancel_order.py`:

```python
"""cancel_order: never gates; idempotent; INVALID_TICKET on unknown."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mt5_mcp.server import build_server
from tests.fakes import (
    FakeAccountInfo, FakeMT5, FakeOrder, FakeOrderSendResult, FakeSymbolInfo,
    FakeTerminalInfo, ORDER_TYPE_BUY_LIMIT, TRADE_RETCODE_DONE,
)


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo()
    fake._symbol_info = {"EURUSD": FakeSymbolInfo(name="EURUSD", visible=True)}
    fake._orders_get = (
        FakeOrder(ticket=77, symbol="EURUSD", type=ORDER_TYPE_BUY_LIMIT,
                  price_open=1.0700, volume_initial=0.1, volume_current=0.1),
    )
    fake._order_send = FakeOrderSendResult(retcode=TRADE_RETCODE_DONE,
                                            order=77, volume=0.1)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[policy]\nauto_approve_notional = "0"\n\n'
        f'[idempotency]\npath = "{(tmp_path / "i.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "a.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_cancel_pending_order_succeeds(server_and_mt5):
    server, fake = server_and_mt5
    out = _call(server, "cancel_order", ticket=77)
    assert out["success"] is True
    sent = fake.order_send_calls[0]
    assert sent["action"] == fake.TRADE_ACTION_REMOVE
    assert sent["order"] == 77


def test_cancel_unknown_returns_invalid_ticket(server_and_mt5):
    server, fake = server_and_mt5
    fake._orders_get = ()
    out = _call(server, "cancel_order", ticket=99999)
    assert out["error"]["code"] == "INVALID_TICKET"


def test_cancel_idempotency_replay(server_and_mt5):
    server, fake = server_and_mt5
    out1 = _call(server, "cancel_order", ticket=77, idempotency_key="k1")
    assert out1["replayed"] is False
    out2 = _call(server, "cancel_order", ticket=77, idempotency_key="k1")
    assert out2["replayed"] is True
    assert len(fake.order_send_calls) == 1
```

`TRADE_ACTION_REMOVE = 8` — add to `tests/fakes.py` and `FakeMT5` in this task.

- [ ] **Step 2: Run tests — expect failure**

Run: `py -m pytest tests/test_tools_cancel_order.py -v`
Expected: tool not registered.

- [ ] **Step 3: Append `cancel_order` to `src/mt5_mcp/tools/orders.py`**

Inside `register()`, after `modify_order`:

```python
    @mcp.tool()
    @error_envelope
    def cancel_order(
        ticket: int,
        idempotency_key: str | None = None,
    ) -> dict:
        """Cancel a pending order by ticket. No consent gate (reduces exposure)."""
        from mt5_mcp.types import CancelOrderRequest
        from mt5_mcp.errors import invalid_ticket_error

        ctx = get_context()
        req = CancelOrderRequest(ticket=ticket, idempotency_key=idempotency_key)
        orders = ctx.client.call(lambda m: m.orders_get(ticket=ticket))
        if not orders:
            raise MT5Error(invalid_ticket_error(ticket=ticket, kind="order"))
        target = orders[0]
        symbol = target.symbol

        with ctx.policy.guard(
            "cancel_order", req,
            requires_approval=False,
            preflight_inputs=None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5 = ctx.client.mt5
            mt5_dict = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(ticket),
            }
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="cancel_order", symbol=symbol,
                request_volume=Decimal(str(getattr(target, "volume_current", 0))),
            )
```

Update `tests/fakes.py`:

```python
TRADE_ACTION_REMOVE = 8
```

And on `FakeMT5`:

```python
TRADE_ACTION_REMOVE: int = TRADE_ACTION_REMOVE
```

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_tools_cancel_order.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Run the full suite**

Run: `py -m pytest -q`
Expected: all green. Test count should be ~91 + ~50 new ≈ 140.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/tools/orders.py tests/test_tools_cancel_order.py tests/fakes.py
git commit -m "feat(phase-2): add cancel_order tool"
```

---

## Task 17: Extend `doctor` CLI with one place_order + close_position round-trip

**Wave 8 — parallel with T18.** Depends on Wave 7 complete.

**Files:**
- Modify: `src/mt5_mcp/cli/doctor.py`
- Modify: `tests/test_cli_doctor.py`

- [ ] **Step 1: Read the existing doctor command**

Run: `cat C:/projects/mt5-trading-mcp/src/mt5_mcp/cli/doctor.py`
The existing checks call read tools. Phase 2 adds two more: `place_order` (1 micro-lot market) and `close_position` (the same ticket).

- [ ] **Step 2: Write a failing test**

Append to `tests/test_cli_doctor.py`:

```python
def test_doctor_includes_place_and_close_smoke(tmp_path: Path, capsys, monkeypatch):
    """The doctor smoke check should call place_order and close_position
    against the FakeMT5 stack so a future regression in the round-trip is
    caught even without a live terminal."""
    from mt5_mcp.cli import doctor as doctor_mod

    # The doctor uses the live build_context; tests inject a fake by
    # monkeypatching `_make_module` (or the equivalent factory hook).
    # Adjust this hook name to match what the existing doctor uses;
    # see step 3 for the actual implementation.

    # Smoke: just call main() and check the output mentions both checks.
    rc = doctor_mod.main([
        "--config", str(tmp_path / "config.toml"),
        "--smoke-trade",
    ])
    out = capsys.readouterr().out
    assert "place_order" in out
    assert "close_position" in out
    assert rc in (0, 1)  # green or yellow; either is fine for the test
```

The test signature assumes the doctor accepts `--smoke-trade`. If today's `main()` has a simpler signature, adjust. The point is: a CLI flag opts the user into the round-trip (off by default to avoid placing real orders during a casual `doctor`).

- [ ] **Step 3: Update `src/mt5_mcp/cli/doctor.py`**

Open the existing file. After the existing read-tool checks, add:

```python
def _smoke_trade(server) -> bool:
    """Place a 0.01 lot market on EURUSD and immediately close it.

    Returns True on success. ANY failure returns False — this is a smoke
    test, not a benchmark. Output goes through the same [PASS]/[FAIL]
    formatter as the read-tool checks.
    """
    place = server._tool_manager.get_tool("place_order").fn(
        symbol="EURUSD", side="buy", type="market", volume="0.01",
        idempotency_key=f"doctor-{int(time.time())}",
    )
    if "error" in place:
        print(f"[FAIL] place_order: {place['error']['code']}")
        return False
    if "request_id" in place:
        print(f"[SKIP] place_order returned approval preview "
              f"(auto_approve_notional too low for smoke?)")
        return True
    ticket = place["ticket"]
    print(f"[PASS] place_order ticket={ticket}")

    close = server._tool_manager.get_tool("close_position").fn(
        ticket=ticket,
        idempotency_key=f"doctor-close-{int(time.time())}",
    )
    if "error" in close or not close.get("success"):
        print(f"[FAIL] close_position: {close.get('error', {}).get('code', '?')}")
        return False
    print(f"[PASS] close_position ticket={ticket}")
    return True
```

Wire it into the CLI flag handling so `python -m mt5_mcp doctor --smoke-trade` runs the round-trip. Without the flag, the read-only smoke checks run as today.

- [ ] **Step 4: Run tests — expect pass**

Run: `py -m pytest tests/test_cli_doctor.py -v`
Expected: existing + new tests pass.

- [ ] **Step 5: (Optional) live smoke check**

If a demo MT5 is reachable: `python -m mt5_mcp doctor --smoke-trade`
Expected: `[PASS] place_order ticket=...` and `[PASS] close_position ticket=...`.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/cli/doctor.py tests/test_cli_doctor.py
git commit -m "feat(phase-2): doctor --smoke-trade does a live place+close round-trip"
```

---

## Task 18: Update `CLAUDE.md` with Phase-2 patterns and gotchas

**Wave 8 — parallel with T17.** No code dependency.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the "Status" line at the top**

Replace:

```markdown
**Status (last updated April 2026):** Phase 1 complete. Tag `phase-1-complete` ...
```

with:

```markdown
**Status (last updated April 2026):** Phase 2 complete. Tag `phase-2-complete` marks the version with the four mutating tools + policy engine landed; ~140 unit tests; doctor `--smoke-trade` round-trip green against the local MT5. Phase 3 picks up Resources + HTTP transport.
```

- [ ] **Step 2: Update "What Phase 1 shipped" → "What Phase 2 added"**

After the existing "What Phase 1 shipped" paragraph, add:

```markdown
## What Phase 2 added

Four mutating tools (`place_order`, `modify_order`, `cancel_order`, `close_position`), a `PolicyEngine` (`src/mt5_mcp/policy/`) handling preflight limits / consent gating / idempotency / audit logging, SQLite-backed idempotency replay (per-OS path via `platformdirs`), append-only JSONL audit log with size-based rotation, ~50 new unit tests, and `doctor --smoke-trade` for live-terminal verification.
```

- [ ] **Step 3: Add new "Critical patterns" entries**

In the "Critical patterns Phase 2 MUST follow" section header, change to "Critical patterns Phase 3 MUST follow" and add new entries (after pattern 2b — keep existing patterns 1, 2, 2b, 3, 4, 5, 6 intact):

```markdown
### 7. Mutating tools route through `ctx.policy.guard(...)`

Every mutating tool body computes `requires_approval` itself (gate logic varies by action — notional for place/close, SL-widening for modify, never for cancel) and passes the boolean to the engine. The engine handles the retry mechanism, idempotency, and audit; the tool body is just adapter prep + `with ctx.policy.guard(...)` + `g.execute(...)` + `g.finalize(...)`.

```python
with ctx.policy.guard(
    "place_order", req,
    requires_approval=notional >= cfg.policy.auto_approve_notional,
    preview_factory=build_preview if requires_approval else None,
    preflight_inputs=PreflightInputs(notional=notional),
    current_price=ref_price if approval_confirmed else None,
    symbol_point=Decimal(str(info.point)) if approval_confirmed else None,
) as g:
    if g.short_circuit is not None:
        return g.short_circuit
    g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
    return g.finalize(order_result_from_mt5_response, request_echo=...,
                       action="place_order", symbol=symbol,
                       request_volume=req.volume)
```

### 8. Storage paths come from config — never hard-code

Idempotency DB and audit JSONL paths default to `platformdirs.user_data_dir("mt5-mcp")`. Tests MUST pass `config_path=tmp_path/"config.toml"` to `build_server(...)` to redirect both files into a sandboxed location — otherwise the tests pollute the real `~/.local/share/mt5-mcp/` (or `%LOCALAPPDATA%\mt5-mcp\`).

### 9. Production code MUST NOT import from `tests.`

A copy-paste hazard in Phase 2: tool implementations briefly imported `POSITION_TYPE_BUY` from `tests.fakes` because the constant names matched. The fix is always `ctx.client.mt5.POSITION_TYPE_BUY` — the live module exposes the same constants.

### 10. `request_hash` excludes `approval_*` fields

Idempotency hashes the canonical JSON of the request EXCLUDING `approval_confirmed` and `approval_request_id`. This makes "send the same trade twice with the same idempotency key" return the cached result, regardless of whether the second call carried an approval token. Don't change this without thinking through retry semantics.
```

- [ ] **Step 4: Update the "Phase 1 carryover — resolved" section**

Rename to "Phase 1 + Phase 2 carryover" and append:

```markdown
## Phase 2 carryover (deferred to Phase 3+)

- **Background TTL sweeper** for idempotency. In-band cleanup is sufficient at expected request volumes; revisit if the DB grows unbounded under heavy load.
- **Audit log compression / archival CLI**. Operators rotate manually; a `mt5-mcp audit prune` command is reasonable Phase 4 polish.
- **`pick_filling_mode` improvements** beyond FOK/IOC/RETURN — broker-specific edge cases may surface during Phase 3 customer onboarding.
- **Multi-leg / OCO / partial-fill orchestration** — explicitly out of scope for v1.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(phase-2): document policy.guard pattern and Phase-2 gotchas"
```

---

## Task 19: Final verification + tag `phase-2-complete` + push

**Wave 9 — sequential after all of Wave 8.** No code changes.

**Files:** none.

- [ ] **Step 1: Run the full suite, deprecation-warnings strict**

Run: `py -m pytest -q`
Expected: all green. ~140 tests in <3 s.

Run: `py -m pytest -W error::DeprecationWarning -q`
Expected: all green. No new deprecation warnings since Phase 1's clean baseline.

- [ ] **Step 2: Run `mypy` (or `pyright`) if configured**

Run: `py -m mypy src/mt5_mcp` (skip if not configured)
Expected: no new errors.

- [ ] **Step 3: Run the live doctor smoke**

Run: `python -m mt5_mcp doctor --smoke-trade`
Expected (with terminal up): `[PASS]` for all 8 read checks + `[PASS] place_order ticket=...` + `[PASS] close_position ticket=...`. If MT5 is offline, skip.

- [ ] **Step 4: Confirm `git status` is clean**

Run: `git status -sb`
Expected: `## main...origin/main` with no uncommitted changes (architecture file may have Vincent's earlier in-progress edit; ignore unless you want to roll it in).

- [ ] **Step 5: Tag and push**

```bash
git tag phase-2-complete -m "Phase 2 complete: mutating tools + policy engine"
git push origin main
git push origin phase-2-complete
```

- [ ] **Step 6: Verify origin has the tag**

Run: `git ls-remote --tags origin | grep phase-2`
Expected: one line referencing `phase-2-complete`.

- [ ] **Step 7: No commit** — Wave 9 only tags.

---

## Definition of done (Phase 2)

- All four mutating tools registered, callable end-to-end against `FakeMT5`.
- `PolicyEngine` covers preflight + consent + idempotency + audit, with isolated unit tests for each module.
- Test count grows from 91 to ~140; full suite green in <3 s; zero deprecation warnings.
- `doctor --smoke-trade` round-trip passes against the local MT5.
- Architecture doc §8.* reconciled (HMAC removed, "soft" → "pre-flight" rename, platformdirs documented).
- CLAUDE.md "Critical patterns" updated with the `ctx.policy.guard(...)` pattern, the path-config requirement, and the no-`tests.`-imports rule.
- Tagged `phase-2-complete`; commit pushed to `main`.

---

## Self-review notes

**Spec coverage (every spec section maps to ≥1 task):**

| Spec § | Task(s) |
|---|---|
| 3 File layout | T1, T7, T11, T12 |
| 4 Type system | T2 |
| 5 PolicyEngine API | T11 |
| 6 Tool body walkthrough | T13 |
| 7 Approval-gate semantics | T13, T14, T15 (gate triggers per action) |
| 7 Hard refusals | T10 (preflight) |
| 7 Daily P&L formula | T10 inputs.running_daily_realised_pnl + comments |
| 7 Retry tolerance | T9 validate_retry |
| 8 Idempotency store | T7, T11 (engine integration) |
| 9 Audit log | T8, T11 (engine writes lines) |
| 10 Error codes | T3 (factories), T7/T9/T10 (raisers), T11 (engine paths) |
| 11 Testing strategy | T5 (fakes), each tool task |
| 12 Doc reconciliation | T16-arch |
| 13 Out of scope | T18 (CLAUDE.md notes) |
| 14 Definition of done | T19 |

**Parallelism summary:**
- Wave 1 (6 tasks): T1, T2, T3, T4, T5, T16-arch — all parallel.
- Wave 2 (1 task): T6 — depends on T2.
- Wave 3 (4 tasks): T7, T8, T9, T10 — all parallel after Wave 1+2.
- Wave 4 (1 task): T11 — sequential.
- Wave 5 (1 task): T12 — sequential.
- Wave 6 (2 tasks): T13, T14 — parallel (different files).
- Wave 7 (2 tasks): T15, T16b — sequential (same file as T13).
- Wave 8 (2 tasks): T17, T18 — parallel.
- Wave 9 (1 task): T19 — sequential.

If a subagent runner is dispatching, the critical path is: Wave 1 → Wave 2 → Wave 3 → Wave 4 → Wave 5 → Wave 6 → Wave 7 → Wave 8 → Wave 9. Wave 1's six tasks collapse to roughly the longest of them (T2 or T16-arch). Waves 3, 6, 8 each get parallel speedup.











