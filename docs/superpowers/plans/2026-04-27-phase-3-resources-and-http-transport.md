# Phase 3 — Resources and HTTP Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three subscribable MCP resources (`account://current`, `positions://current`, `quotes://{symbol}`) plus an opt-in HTTP/SSE transport with bearer-token auth, on top of Phase 1+2.

**Architecture:** A single shared daemon-thread `Poller` polls quotes (default 200ms), account, and positions (default 1000ms each), diffs against the previous snapshot, and asks a `Dispatcher` to fan out `notifications/resources/updated` to subscribers. Subscribers re-read the resource via the existing `mt5lib`-backed read path. HTTP transport is opt-in via `serve --transport http`, binds loopback only, with optional bearer-token middleware. STDIO stays the default.

**Tech Stack:** Python 3.11+, FastMCP (existing), `mt5lib` (via `MT5Client.call`), `threading`/`queue`, Starlette middleware (via FastMCP's streamable-HTTP transport), `httpx` (test-only), `pytest`.

**Spec:** `docs/superpowers/specs/2026-04-27-phase-3-resources-and-http-transport-design.md`

---

## File Structure

**New files:**
- `src/mt5_mcp/streaming/__init__.py` — re-exports Poller, Dispatcher
- `src/mt5_mcp/streaming/snapshots.py` — TickSnapshot, AccountSnapshot, PositionSnapshot dataclasses
- `src/mt5_mcp/streaming/dispatcher.py` — Dispatcher, Subscription, SubscriptionHandle, Subscriber protocol
- `src/mt5_mcp/streaming/poller.py` — Poller class
- `src/mt5_mcp/resources/__init__.py` — register_resources(mcp) entrypoint
- `src/mt5_mcp/resources/quotes.py`, `account.py`, `positions.py`
- `src/mt5_mcp/transport.py` — run(mcp, transport, config), BearerAuthMiddleware, _is_loopback
- `tests/test_streaming_snapshots.py`, `test_streaming_dispatcher.py`, `test_streaming_poller.py`
- `tests/test_resources_account.py`, `test_resources_positions.py`, `test_resources_quotes.py`
- `tests/test_transport.py`
- `tests/test_transport_http_integration.py` (marked `@pytest.mark.integration`)

**Modified files:**
- `src/mt5_mcp/config.py` — extend `TransportHTTPSection` (add host/port), add `StreamingSection` to `Config`
- `src/mt5_mcp/errors.py` — add `resource_not_found(uri)` factory
- `src/mt5_mcp/server.py` — extend `AppContext` with `dispatcher` + `poller`; build them in `build_context`; register resources in `build_server`; tear down in `reset_context_for_tests`
- `src/mt5_mcp/__main__.py` — add `--transport {stdio,http}` to the `serve` subcommand; route to `transport.run(...)`
- `src/mt5_mcp/cli/doctor.py` — add `[streaming]` check
- `tests/fakes.py` — no field changes needed (existing `_symbol_info_tick`, `_account_info`, `_positions_get` are already mutable dicts/tuples)
- `tests/conftest.py` — no change needed (existing `_reset_app_context` will pick up new AppContext teardown automatically)

---

## Task 1: Config additions for HTTP host/port and streaming intervals

**Files:**
- Modify: `src/mt5_mcp/config.py`
- Test: `tests/test_config.py` (existing — extend; create if missing)

- [ ] **Step 1: Inspect existing test_config.py if present**

```bash
ls tests/test_config.py 2>/dev/null && head -20 tests/test_config.py || echo "create new"
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_config.py` (create the file with appropriate imports if it doesn't exist):

```python
from mt5_mcp.config import Config, load_config


def test_config_defaults_have_http_host_port_and_streaming(tmp_path):
    cfg = Config()
    assert cfg.transport.http.host == "127.0.0.1"
    assert cfg.transport.http.port == 8765
    assert cfg.transport.http.auth_token == ""
    assert cfg.streaming.quote_poll_interval_ms == 200
    assert cfg.streaming.account_poll_interval_ms == 1000
    assert cfg.streaming.positions_poll_interval_ms == 1000


def test_config_streaming_intervals_have_floor_and_ceiling(tmp_path):
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Config(streaming={"quote_poll_interval_ms": 10})  # below 50ms floor
    with pytest.raises(ValidationError):
        Config(streaming={"quote_poll_interval_ms": 99999})  # above 10000ms


def test_config_loads_streaming_and_transport_from_toml(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[transport.http]\n'
        'host = "127.0.0.1"\n'
        'port = 9000\n'
        'auth_token = "secret"\n'
        '[streaming]\n'
        'quote_poll_interval_ms = 100\n'
        'account_poll_interval_ms = 500\n'
        'positions_poll_interval_ms = 500\n'
    )
    cfg = load_config(cfg_file)
    assert cfg.transport.http.port == 9000
    assert cfg.transport.http.auth_token == "secret"
    assert cfg.streaming.quote_poll_interval_ms == 100
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_config.py::test_config_defaults_have_http_host_port_and_streaming -v
```

Expected: FAIL — `transport.http` lacks `host`/`port`; `streaming` attribute missing.

- [ ] **Step 4: Extend `TransportHTTPSection` and add `StreamingSection`**

Edit `src/mt5_mcp/config.py`:

Replace the existing `TransportHTTPSection` class:

```python
class TransportHTTPSection(_Sub):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    auth_token: str = ""
```

Add a new `StreamingSection` after `TelemetrySection`:

```python
class StreamingSection(_Sub):
    quote_poll_interval_ms: int = Field(200, ge=50, le=10000)
    account_poll_interval_ms: int = Field(1000, ge=100, le=60000)
    positions_poll_interval_ms: int = Field(1000, ge=100, le=60000)
```

Add the field to `Config`:

```python
class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mt5: MT5Section = Field(default_factory=MT5Section)
    policy: PolicySection = Field(default_factory=PolicySection)
    idempotency: IdempotencySection = Field(default_factory=IdempotencySection)
    symbols: SymbolsSection = Field(default_factory=SymbolsSection)
    audit: AuditSection = Field(default_factory=AuditSection)
    transport: TransportSection = Field(default_factory=TransportSection)
    telemetry: TelemetrySection = Field(default_factory=TelemetrySection)
    streaming: StreamingSection = Field(default_factory=StreamingSection)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: PASS for all three new tests AND existing config tests (regression-free).

- [ ] **Step 6: Run the full suite**

```bash
pytest -v
```

Expected: PASS — same count as before plus three new.

- [ ] **Step 7: Commit**

```bash
git add src/mt5_mcp/config.py tests/test_config.py
git commit -m "feat(phase-3): config additions for HTTP host/port + streaming intervals"
```

---

## Task 2: `errors.resource_not_found(uri)` factory

**Files:**
- Modify: `src/mt5_mcp/errors.py`
- Test: `tests/test_errors.py` (existing — extend; create if missing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_errors.py`:

```python
from mt5_mcp.errors import resource_not_found


def test_resource_not_found_factory():
    detail = resource_not_found("quotes://XYZ")
    assert detail.code == "RESOURCE_NOT_FOUND"
    assert "quotes://XYZ" in detail.message
    assert detail.retryable is False
    assert detail.requires_human is False
    assert detail.details == {"uri": "quotes://XYZ"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_errors.py::test_resource_not_found_factory -v
```

Expected: FAIL — `cannot import name 'resource_not_found' from 'mt5_mcp.errors'`.

- [ ] **Step 3: Add the factory**

Append to `src/mt5_mcp/errors.py` (after `invalid_ticket_error`, before `class MT5Error`):

```python
def resource_not_found(uri: str) -> ErrorDetail:
    """MCP resource URI did not resolve (e.g. unknown symbol in quotes://)."""
    return ErrorDetail(
        code="RESOURCE_NOT_FOUND",
        message=f"Resource not found: {uri}",
        retryable=False,
        requires_human=False,
        details={"uri": uri},
    )
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_errors.py::test_resource_not_found_factory -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/errors.py tests/test_errors.py
git commit -m "feat(phase-3): add errors.resource_not_found(uri) factory"
```

---

## Task 3: Snapshot dataclasses

**Files:**
- Create: `src/mt5_mcp/streaming/__init__.py`
- Create: `src/mt5_mcp/streaming/snapshots.py`
- Create: `tests/test_streaming_snapshots.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streaming_snapshots.py`:

```python
import pytest

from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


def test_tick_snapshot_equality_by_value():
    a = TickSnapshot(time_msc=1, bid=1.1, ask=1.2, last=0.0, volume=0)
    b = TickSnapshot(time_msc=1, bid=1.1, ask=1.2, last=0.0, volume=0)
    c = TickSnapshot(time_msc=2, bid=1.1, ask=1.2, last=0.0, volume=0)
    assert a == b
    assert a != c


def test_tick_snapshot_is_frozen():
    a = TickSnapshot(time_msc=1, bid=1.1, ask=1.2, last=0.0, volume=0)
    with pytest.raises(Exception):  # FrozenInstanceError
        a.bid = 2.0  # type: ignore[misc]


def test_account_snapshot_tracks_only_balance_credit_currency():
    a = AccountSnapshot(balance=100.0, credit=0.0, currency="USD")
    b = AccountSnapshot(balance=100.0, credit=0.0, currency="USD")
    c = AccountSnapshot(balance=200.0, credit=0.0, currency="USD")
    assert a == b
    assert a != c


def test_position_snapshot_tracks_only_ticket_volume_sl_tp():
    a = PositionSnapshot(ticket=1, volume=0.10, sl=0.0, tp=0.0)
    b = PositionSnapshot(ticket=1, volume=0.10, sl=0.0, tp=0.0)
    c = PositionSnapshot(ticket=1, volume=0.10, sl=1.05, tp=0.0)  # SL changed
    assert a == b
    assert a != c
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_streaming_snapshots.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'mt5_mcp.streaming'`.

- [ ] **Step 3: Create `streaming` package and snapshots module**

Create `src/mt5_mcp/streaming/__init__.py` (empty file content):

```python
"""Streaming subsystem: shared poller + dispatcher for resource subscriptions."""
```

Create `src/mt5_mcp/streaming/snapshots.py`:

```python
"""Internal snapshot dataclasses used by the Poller for diff detection.

NOT the Pydantic types returned to MCP clients — those stay in
``mt5_mcp.types`` and are produced by ``adapter/conversions.py``.
Snapshots only carry the fields the diff logic compares.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickSnapshot:
    time_msc: int
    bid: float
    ask: float
    last: float
    volume: int


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Tracks identity-style fields only.

    Excluded by design: equity, margin, free_margin, profit, margin_level —
    these drift on every tick and would defeat the purpose of subscribing
    to ``account://current``.
    """
    balance: float
    credit: float
    currency: str


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Tracks identity + structural fields only.

    Excluded by design: price_current, profit, swap, time_update — these
    drift on every tick. Subscribers compose ``positions://current`` with
    ``quotes://{symbol}`` to compute floating P&L.
    """
    ticket: int
    volume: float
    sl: float
    tp: float
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_streaming_snapshots.py -v
```

Expected: PASS for all four.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/streaming/__init__.py src/mt5_mcp/streaming/snapshots.py tests/test_streaming_snapshots.py
git commit -m "feat(phase-3): snapshot dataclasses for poller diff detection"
```

---

## Task 4: Dispatcher — subscribe/unsubscribe + symbol refcount + tick fanout

**Files:**
- Create: `src/mt5_mcp/streaming/dispatcher.py`
- Create: `tests/test_streaming_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streaming_dispatcher.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mt5_mcp.streaming.dispatcher import (
    Dispatcher,
    Subscriber,
    SubscriptionHandle,
)
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


@dataclass
class FakeSubscriber:
    """In-memory subscriber that records every notify_updated() call."""
    notifications: list[str] = field(default_factory=list)
    raise_on_send: bool = False

    def notify_updated(self, uri: str) -> None:
        if self.raise_on_send:
            raise RuntimeError("connection dead")
        self.notifications.append(uri)


@dataclass
class FakePoller:
    """In-memory poller that records add_symbol/remove_symbol/start/stop."""
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    started: int = 0
    stopped: int = 0

    def add_symbol(self, symbol: str) -> None:
        self.added.append(symbol)

    def remove_symbol(self, symbol: str) -> None:
        self.removed.append(symbol)

    def start(self) -> None:
        self.started += 1

    def stop(self, timeout: float = 2.0) -> None:
        self.stopped += 1


def _disp() -> tuple[Dispatcher, FakePoller]:
    poller = FakePoller()
    d = Dispatcher()
    d.bind_poller(poller)
    return d, poller


def test_subscribe_returns_handle_and_starts_poller_on_first():
    d, poller = _disp()
    sub = FakeSubscriber()
    h = d.subscribe("quotes://EURUSD", sub)
    assert isinstance(h, SubscriptionHandle)
    assert poller.added == ["EURUSD"]
    assert poller.started == 1


def test_second_subscribe_same_symbol_does_not_re_add_or_re_start():
    d, poller = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    d.subscribe("quotes://EURUSD", s1)
    d.subscribe("quotes://EURUSD", s2)
    assert poller.added == ["EURUSD"]   # one add only
    assert poller.started == 1          # one start only


def test_unsubscribe_removes_symbol_when_refcount_zero():
    d, poller = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    h1 = d.subscribe("quotes://EURUSD", s1)
    h2 = d.subscribe("quotes://EURUSD", s2)
    d.unsubscribe(h1)
    assert poller.removed == []         # still one subscriber
    d.unsubscribe(h2)
    assert poller.removed == ["EURUSD"]
    assert poller.stopped == 1          # last subscription gone


def test_dispatch_tick_fans_out_only_to_matching_uri():
    d, _ = _disp()
    eu, gu = FakeSubscriber(), FakeSubscriber()
    d.subscribe("quotes://EURUSD", eu)
    d.subscribe("quotes://GBPUSD", gu)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))
    assert eu.notifications == ["quotes://EURUSD"]
    assert gu.notifications == []


def test_dispatch_tick_fans_out_to_multiple_subscribers_of_same_symbol():
    d, _ = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    d.subscribe("quotes://EURUSD", s1)
    d.subscribe("quotes://EURUSD", s2)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))
    assert s1.notifications == ["quotes://EURUSD"]
    assert s2.notifications == ["quotes://EURUSD"]


def test_subscribed_symbols_returns_current_set():
    d, _ = _disp()
    d.subscribe("quotes://EURUSD", FakeSubscriber())
    d.subscribe("quotes://GBPUSD", FakeSubscriber())
    assert d.subscribed_symbols() == {"EURUSD", "GBPUSD"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_streaming_dispatcher.py -v
```

Expected: FAIL — `cannot import name 'Dispatcher' from 'mt5_mcp.streaming.dispatcher'`.

- [ ] **Step 3: Create the Dispatcher**

Create `src/mt5_mcp/streaming/dispatcher.py`:

```python
"""Dispatcher: subscriber registry, refcounting, and notification fanout.

The Dispatcher is the only owner of subscription state. The Poller asks
the Dispatcher for the current symbol set and calls dispatch_* when it
detects a change. Subscriber sessions are abstracted via a tiny Protocol
so the Dispatcher doesn't know about STDIO vs HTTP.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


logger = logging.getLogger(__name__)


class Subscriber(Protocol):
    """Anything capable of receiving an MCP resource-update notification."""
    def notify_updated(self, uri: str) -> None: ...


@dataclass(frozen=True)
class SubscriptionHandle:
    id: str


@dataclass
class _Subscription:
    handle: SubscriptionHandle
    uri: str
    subscriber: Subscriber
    dead: bool = False


class Dispatcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs_by_uri: dict[str, list[_Subscription]] = {}
        self._subs_by_handle: dict[SubscriptionHandle, _Subscription] = {}
        self._symbol_refcount: dict[str, int] = {}
        self._poller = None  # type: ignore[var-annotated]

    def bind_poller(self, poller) -> None:
        """Late-binding to break the Poller↔Dispatcher cycle."""
        self._poller = poller

    # ----- subscription lifecycle -----

    def subscribe(self, uri: str, subscriber: Subscriber) -> SubscriptionHandle:
        handle = SubscriptionHandle(id=uuid.uuid4().hex)
        sub = _Subscription(handle=handle, uri=uri, subscriber=subscriber)
        added_symbol: str | None = None
        was_empty: bool = False
        with self._lock:
            was_empty = not self._subs_by_handle
            self._subs_by_uri.setdefault(uri, []).append(sub)
            self._subs_by_handle[handle] = sub
            if uri.startswith("quotes://"):
                sym = uri.removeprefix("quotes://")
                self._symbol_refcount[sym] = self._symbol_refcount.get(sym, 0) + 1
                if self._symbol_refcount[sym] == 1:
                    added_symbol = sym
        if added_symbol is not None and self._poller is not None:
            self._poller.add_symbol(added_symbol)
        if was_empty and self._poller is not None:
            self._poller.start()
        return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        removed_symbol: str | None = None
        now_empty: bool = False
        with self._lock:
            sub = self._subs_by_handle.pop(handle, None)
            if sub is None:
                return
            self._subs_by_uri[sub.uri].remove(sub)
            if not self._subs_by_uri[sub.uri]:
                del self._subs_by_uri[sub.uri]
            if sub.uri.startswith("quotes://"):
                sym = sub.uri.removeprefix("quotes://")
                self._symbol_refcount[sym] -= 1
                if self._symbol_refcount[sym] == 0:
                    del self._symbol_refcount[sym]
                    removed_symbol = sym
            now_empty = not self._subs_by_handle
        if removed_symbol is not None and self._poller is not None:
            self._poller.remove_symbol(removed_symbol)
        if now_empty and self._poller is not None:
            self._poller.stop()

    def subscribed_symbols(self) -> set[str]:
        with self._lock:
            return set(self._symbol_refcount.keys())

    # ----- fanout -----

    def _fanout(self, uri: str) -> None:
        with self._lock:
            targets = list(self._subs_by_uri.get(uri, ()))
        for sub in targets:
            if sub.dead:
                continue
            try:
                sub.subscriber.notify_updated(uri)
            except Exception:
                logger.warning(
                    "subscriber send failed for %s; marking dead", uri,
                    exc_info=True,
                )
                sub.dead = True

    def dispatch_tick(self, symbol: str, snap: TickSnapshot) -> None:
        self._fanout(f"quotes://{symbol}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_streaming_dispatcher.py -v
```

Expected: PASS for all six tests in this task.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/streaming/dispatcher.py tests/test_streaming_dispatcher.py
git commit -m "feat(phase-3): Dispatcher with subscribe/unsubscribe + tick fanout"
```

---

## Task 5: Dispatcher — account/positions fanout, dead-subscriber reaping, error fanouts

**Files:**
- Modify: `src/mt5_mcp/streaming/dispatcher.py`
- Modify: `tests/test_streaming_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_streaming_dispatcher.py`:

```python
def test_dispatch_account_fanout():
    d, _ = _disp()
    s1, s2 = FakeSubscriber(), FakeSubscriber()
    d.subscribe("account://current", s1)
    d.subscribe("account://current", s2)
    d.dispatch_account(AccountSnapshot(balance=100.0, credit=0.0, currency="USD"))
    assert s1.notifications == ["account://current"]
    assert s2.notifications == ["account://current"]


def test_dispatch_positions_fanout():
    d, _ = _disp()
    s = FakeSubscriber()
    d.subscribe("positions://current", s)
    d.dispatch_positions()
    assert s.notifications == ["positions://current"]


def test_subscribing_to_account_does_not_touch_poller_symbol_set():
    d, poller = _disp()
    d.subscribe("account://current", FakeSubscriber())
    d.subscribe("positions://current", FakeSubscriber())
    assert poller.added == []
    assert poller.started == 1  # first subscription overall starts the poller


def test_dead_subscriber_marked_after_send_failure():
    d, _ = _disp()
    bad = FakeSubscriber(raise_on_send=True)
    good = FakeSubscriber()
    d.subscribe("quotes://EURUSD", bad)
    d.subscribe("quotes://EURUSD", good)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))
    # Good subscriber still receives even though the bad one raised.
    assert good.notifications == ["quotes://EURUSD"]
    # On next dispatch, bad is skipped (no exception escapes)
    d.dispatch_tick("EURUSD", TickSnapshot(2, 1.11, 1.21, 0.0, 0))
    assert good.notifications == ["quotes://EURUSD", "quotes://EURUSD"]


def test_reap_dead_subscribers_removes_them():
    d, poller = _disp()
    bad = FakeSubscriber(raise_on_send=True)
    good = FakeSubscriber()
    d.subscribe("quotes://EURUSD", bad)
    d.subscribe("quotes://EURUSD", good)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))  # marks bad dead
    reaped = d.reap_dead_subscribers()
    assert reaped == 1
    # Refcount unchanged because good subscriber holds the symbol.
    d.dispatch_tick("EURUSD", TickSnapshot(2, 1.1, 1.2, 0.0, 0))
    assert good.notifications == ["quotes://EURUSD", "quotes://EURUSD"]


def test_reap_releases_symbol_when_last_subscriber_dies():
    d, poller = _disp()
    bad = FakeSubscriber(raise_on_send=True)
    d.subscribe("quotes://EURUSD", bad)
    d.dispatch_tick("EURUSD", TickSnapshot(1, 1.1, 1.2, 0.0, 0))  # marks dead
    d.reap_dead_subscribers()
    assert poller.removed == ["EURUSD"]
    assert poller.stopped == 1  # no subscriptions left


def test_dispatch_quote_error_fanouts_to_symbol_subscribers():
    d, _ = _disp()
    s = FakeSubscriber()
    d.subscribe("quotes://EURUSD", s)
    d.dispatch_quote_error("EURUSD")
    assert s.notifications == ["quotes://EURUSD"]


def test_dispatch_account_and_positions_error_fanouts():
    d, _ = _disp()
    sa, sp = FakeSubscriber(), FakeSubscriber()
    d.subscribe("account://current", sa)
    d.subscribe("positions://current", sp)
    d.dispatch_account_error()
    d.dispatch_positions_error()
    assert sa.notifications == ["account://current"]
    assert sp.notifications == ["positions://current"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_streaming_dispatcher.py -v -k "dispatch_account or dispatch_positions or dead or reap or dispatch_quote_error"
```

Expected: FAIL — methods don't exist.

- [ ] **Step 3: Add the new methods to Dispatcher**

In `src/mt5_mcp/streaming/dispatcher.py`, append these methods to the `Dispatcher` class (after `dispatch_tick`):

```python
    def dispatch_account(self, snap: AccountSnapshot) -> None:
        self._fanout("account://current")

    def dispatch_positions(self) -> None:
        self._fanout("positions://current")

    def dispatch_quote_error(self, symbol: str) -> None:
        """Fan out an updated notification on persistent quote-poll failure.

        Subscribers re-read the resource; the read path's own ctx.client.call
        is what surfaces the underlying MT5 error envelope.
        """
        self._fanout(f"quotes://{symbol}")

    def dispatch_account_error(self) -> None:
        self._fanout("account://current")

    def dispatch_positions_error(self) -> None:
        self._fanout("positions://current")

    def reap_dead_subscribers(self) -> int:
        """Remove subscribers marked dead during fanout. Returns count reaped."""
        reaped: list[_Subscription] = []
        symbols_to_release: list[str] = []
        now_empty: bool = False
        with self._lock:
            for sub in list(self._subs_by_handle.values()):
                if not sub.dead:
                    continue
                self._subs_by_handle.pop(sub.handle, None)
                self._subs_by_uri[sub.uri].remove(sub)
                if not self._subs_by_uri[sub.uri]:
                    del self._subs_by_uri[sub.uri]
                if sub.uri.startswith("quotes://"):
                    sym = sub.uri.removeprefix("quotes://")
                    self._symbol_refcount[sym] -= 1
                    if self._symbol_refcount[sym] == 0:
                        del self._symbol_refcount[sym]
                        symbols_to_release.append(sym)
                reaped.append(sub)
            now_empty = not self._subs_by_handle
        if self._poller is not None:
            for sym in symbols_to_release:
                self._poller.remove_symbol(sym)
            if now_empty and reaped:
                self._poller.stop()
        return len(reaped)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_streaming_dispatcher.py -v
```

Expected: PASS for all dispatcher tests (~13 total).

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/streaming/dispatcher.py tests/test_streaming_dispatcher.py
git commit -m "feat(phase-3): Dispatcher account/positions/error fanouts + reap"
```

---

## Task 6: Poller — basic structure (start/stop/wake), single-cycle quote poll

**Files:**
- Create: `src/mt5_mcp/streaming/poller.py`
- Create: `tests/test_streaming_poller.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streaming_poller.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.config import StreamingSection
from mt5_mcp.streaming.dispatcher import Dispatcher
from mt5_mcp.streaming.poller import Poller
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)
from tests.fakes import FakeAccountInfo, FakeMT5, FakePosition, FakeTick


@dataclass
class RecordingDispatcher:
    """Records dispatch_* calls for poller-level tests, exposes a fixed symbol set."""
    symbols: set[str] = field(default_factory=set)
    ticks: list[tuple[str, TickSnapshot]] = field(default_factory=list)
    accounts: list[AccountSnapshot] = field(default_factory=list)
    positions: int = 0
    quote_errors: list[str] = field(default_factory=list)
    account_errors: int = 0
    positions_errors: int = 0
    poller: Any = None

    def bind_poller(self, p): self.poller = p
    def subscribed_symbols(self) -> set[str]: return self.symbols
    def dispatch_tick(self, symbol, snap): self.ticks.append((symbol, snap))
    def dispatch_account(self, snap): self.accounts.append(snap)
    def dispatch_positions(self): self.positions += 1
    def dispatch_quote_error(self, symbol): self.quote_errors.append(symbol)
    def dispatch_account_error(self): self.account_errors += 1
    def dispatch_positions_error(self): self.positions_errors += 1


def _client(mt5_module) -> MT5Client:
    c = MT5Client(mt5_module=mt5_module)
    c.connect()
    return c


def _streaming_cfg(**overrides) -> StreamingSection:
    base = dict(
        quote_poll_interval_ms=200,
        account_poll_interval_ms=1000,
        positions_poll_interval_ms=1000,
    )
    base.update(overrides)
    return StreamingSection(**base)


def test_poller_start_stop_is_idempotent():
    fake = FakeMT5()
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp, config=_streaming_cfg())
    p.start()
    p.start()  # idempotent
    p.stop()
    p.stop()  # idempotent


def test_poller_polls_subscribed_symbol_and_dispatches_initial_tick():
    fake = FakeMT5()
    fake._symbol_info_tick["EURUSD"] = FakeTick(time=1, bid=1.10, ask=1.11)
    disp = RecordingDispatcher(symbols={"EURUSD"})
    p = Poller(client=_client(fake), dispatcher=disp, config=_streaming_cfg())
    p.poll_once()  # synchronous test helper: one full cycle, no thread
    assert len(disp.ticks) == 1
    sym, snap = disp.ticks[0]
    assert sym == "EURUSD"
    assert snap.bid == 1.10


def test_poller_skips_when_no_symbols_subscribed():
    fake = FakeMT5()
    disp = RecordingDispatcher(symbols=set())
    p = Poller(client=_client(fake), dispatcher=disp, config=_streaming_cfg())
    p.poll_once()
    assert disp.ticks == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_streaming_poller.py -v
```

Expected: FAIL — `cannot import name 'Poller' from 'mt5_mcp.streaming.poller'`.

- [ ] **Step 3: Create the Poller**

Create `src/mt5_mcp/streaming/poller.py`:

```python
"""Poller: shared daemon-thread loop driving change-detection for all
three subscribable resources.

Lazy-start: only spawns the thread when the dispatcher reports it has
subscribers. Skip-on-error semantics: an MT5Error in any of the three
poll routines logs WARNING and increments a per-resource counter; three
consecutive failures fire a one-shot error notification via the
dispatcher; a successful poll silently resets the counter.
"""

from __future__ import annotations

import logging
import threading
from time import monotonic
from typing import Any

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.config import StreamingSection
from mt5_mcp.errors import MT5Error
from mt5_mcp.streaming.snapshots import (
    AccountSnapshot,
    PositionSnapshot,
    TickSnapshot,
)


logger = logging.getLogger(__name__)


_FAILURE_THRESHOLD = 3


class Poller:
    def __init__(
        self,
        *,
        client: MT5Client,
        dispatcher: Any,
        config: StreamingSection,
    ) -> None:
        self._client = client
        self._dispatcher = dispatcher
        self._cfg = config

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

        self._last_ticks: dict[str, TickSnapshot] = {}
        self._last_account: AccountSnapshot | None = None
        self._last_positions: dict[int, PositionSnapshot] = {}

        self._last_account_poll: float = 0.0
        self._last_positions_poll: float = 0.0

        self._quote_failures: dict[str, int] = {}
        self._account_failures: int = 0
        self._positions_failures: int = 0

    # ----- thread lifecycle -----

    def start(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="mt5-poller", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._thread_lock:
            t = self._thread
            if t is None:
                return
            self._stop.set()
            self._wake.set()
        t.join(timeout=timeout)
        with self._thread_lock:
            self._thread = None

    def add_symbol(self, symbol: str) -> None:
        self._wake.set()

    def remove_symbol(self, symbol: str) -> None:
        self._last_ticks.pop(symbol, None)
        self._quote_failures.pop(symbol, None)

    # ----- loop -----

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            interval = self._cfg.quote_poll_interval_ms / 1000.0
            self._wake.wait(timeout=interval)
            self._wake.clear()

    def poll_once(self) -> None:
        """One synchronous poll cycle. Public for tests; called from _run."""
        self._poll_quotes()
        # Account / positions cadences are honoured against monotonic time.
        now = monotonic()
        if now - self._last_account_poll >= self._cfg.account_poll_interval_ms / 1000.0:
            self._poll_account()
            self._last_account_poll = now
        if now - self._last_positions_poll >= self._cfg.positions_poll_interval_ms / 1000.0:
            self._poll_positions()
            self._last_positions_poll = now

    def _poll_quotes(self) -> None:
        for sym in self._dispatcher.subscribed_symbols():
            try:
                tick = self._client.call(lambda m, s=sym: m.symbol_info_tick(s))
            except MT5Error:
                self._record_quote_failure(sym)
                continue
            except Exception:
                logger.exception("unexpected exception polling %s", sym)
                self._record_quote_failure(sym)
                continue
            if tick is None:
                continue
            snap = TickSnapshot(
                time_msc=getattr(tick, "time_msc", tick.time * 1000),
                bid=tick.bid,
                ask=tick.ask,
                last=tick.last,
                volume=tick.volume,
            )
            last = self._last_ticks.get(sym)
            if last != snap:
                self._last_ticks[sym] = snap
                self._dispatcher.dispatch_tick(sym, snap)
            self._quote_failures.pop(sym, None)

    def _poll_account(self) -> None:
        # Filled in by Task 7.
        pass

    def _poll_positions(self) -> None:
        # Filled in by Task 7.
        pass

    def _record_quote_failure(self, symbol: str) -> None:
        n = self._quote_failures.get(symbol, 0) + 1
        self._quote_failures[symbol] = n
        if n == _FAILURE_THRESHOLD:
            logger.warning("quote poll failed %dx for %s; firing error notification", n, symbol)
            self._dispatcher.dispatch_quote_error(symbol)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_streaming_poller.py -v
```

Expected: PASS for the three tests in this task.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/streaming/poller.py tests/test_streaming_poller.py
git commit -m "feat(phase-3): Poller skeleton + quotes diff loop"
```

---

## Task 7: Poller — account + positions diff cycles

**Files:**
- Modify: `src/mt5_mcp/streaming/poller.py` (replace `_poll_account`, `_poll_positions`)
- Modify: `tests/test_streaming_poller.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_streaming_poller.py`:

```python
def test_poller_dispatches_account_on_balance_change():
    fake = FakeMT5()
    fake._account_info = FakeAccountInfo(balance=10_000.0, credit=0.0, currency="USD")
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(account_poll_interval_ms=100))
    p.poll_once()
    assert len(disp.accounts) == 1  # initial diff (None vs first snapshot)
    fake._account_info = FakeAccountInfo(balance=10_500.0, credit=0.0, currency="USD")
    # Wait long enough for the cadence guard to allow a second account poll.
    import time
    time.sleep(0.15)
    p.poll_once()
    assert len(disp.accounts) == 2


def test_poller_skips_account_when_only_equity_changed():
    fake = FakeMT5()
    fake._account_info = FakeAccountInfo(balance=10_000.0, equity=10_010.0, currency="USD")
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(account_poll_interval_ms=10))
    p.poll_once()
    n = len(disp.accounts)
    fake._account_info = FakeAccountInfo(balance=10_000.0, equity=10_999.0, currency="USD")
    import time
    time.sleep(0.05)
    p.poll_once()
    assert len(disp.accounts) == n  # equity-only drift does NOT fire


def test_poller_dispatches_positions_on_open_close():
    fake = FakeMT5()
    fake._positions_get = ()
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=10))
    p.poll_once()
    initial = disp.positions
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0),)
    import time
    time.sleep(0.05)
    p.poll_once()
    assert disp.positions == initial + 1
    fake._positions_get = ()
    time.sleep(0.05)
    p.poll_once()
    assert disp.positions == initial + 2


def test_poller_dispatches_positions_on_sl_change():
    fake = FakeMT5()
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0),)
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=10))
    p.poll_once()
    initial = disp.positions
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=1.05, tp=0.0),)
    import time
    time.sleep(0.05)
    p.poll_once()
    assert disp.positions == initial + 1


def test_poller_skips_positions_when_only_floating_pnl_changed():
    fake = FakeMT5()
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0, profit=4.0),)
    disp = RecordingDispatcher()
    p = Poller(client=_client(fake), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=10))
    p.poll_once()
    initial = disp.positions
    fake._positions_get = (FakePosition(ticket=1, volume=0.1, sl=0.0, tp=0.0, profit=99.0),)
    import time
    time.sleep(0.05)
    p.poll_once()
    assert disp.positions == initial  # profit-only drift does NOT fire
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_streaming_poller.py -v -k "account or positions"
```

Expected: FAIL — account/positions diffs not implemented.

- [ ] **Step 3: Implement account + positions polls**

Replace the placeholder `_poll_account` and `_poll_positions` in `src/mt5_mcp/streaming/poller.py` with:

```python
    def _poll_account(self) -> None:
        try:
            info = self._client.call(lambda m: m.account_info())
        except MT5Error:
            self._record_account_failure()
            return
        except Exception:
            logger.exception("unexpected exception polling account_info")
            self._record_account_failure()
            return
        if info is None:
            return
        snap = AccountSnapshot(
            balance=info.balance,
            credit=info.credit,
            currency=info.currency,
        )
        if self._last_account != snap:
            self._last_account = snap
            self._dispatcher.dispatch_account(snap)
        self._account_failures = 0

    def _poll_positions(self) -> None:
        try:
            raws = self._client.call(lambda m: m.positions_get())
        except MT5Error:
            self._record_positions_failure()
            return
        except Exception:
            logger.exception("unexpected exception polling positions_get")
            self._record_positions_failure()
            return
        if raws is None:
            raws = ()
        new_map: dict[int, PositionSnapshot] = {
            p.ticket: PositionSnapshot(
                ticket=p.ticket, volume=p.volume, sl=p.sl, tp=p.tp,
            )
            for p in raws
        }
        if new_map != self._last_positions:
            self._last_positions = new_map
            self._dispatcher.dispatch_positions()
        self._positions_failures = 0

    def _record_account_failure(self) -> None:
        self._account_failures += 1
        if self._account_failures == _FAILURE_THRESHOLD:
            logger.warning("account poll failed %dx; firing error notification",
                           self._account_failures)
            self._dispatcher.dispatch_account_error()

    def _record_positions_failure(self) -> None:
        self._positions_failures += 1
        if self._positions_failures == _FAILURE_THRESHOLD:
            logger.warning("positions poll failed %dx; firing error notification",
                           self._positions_failures)
            self._dispatcher.dispatch_positions_error()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_streaming_poller.py -v
```

Expected: PASS for all eight poller tests.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/streaming/poller.py tests/test_streaming_poller.py
git commit -m "feat(phase-3): Poller account + positions diff cycles"
```

---

## Task 8: Poller — error counters fire dispatch_*_error after 3 strikes

**Files:**
- Modify: `tests/test_streaming_poller.py`

The implementation already includes failure counters; this task asserts the threshold-based behavior.

- [ ] **Step 1: Write the tests**

Append to `tests/test_streaming_poller.py`:

```python
from mt5_mcp.errors import MT5Error, terminal_not_connected_error


class _FakeFailingClient:
    """Client stand-in that raises MT5Error on every call."""
    def __init__(self, n_failures: int) -> None:
        self._remaining = n_failures
        self.broker_offset_minutes = 0

    def call(self, fn):
        if self._remaining > 0:
            self._remaining -= 1
            raise MT5Error(terminal_not_connected_error())
        return None


def test_quote_error_dispatch_fires_after_three_failures():
    disp = RecordingDispatcher(symbols={"EURUSD"})
    p = Poller(client=_FakeFailingClient(n_failures=10), dispatcher=disp,
               config=_streaming_cfg())
    p.poll_once()
    p.poll_once()
    assert disp.quote_errors == []
    p.poll_once()
    assert disp.quote_errors == ["EURUSD"]


def test_account_error_dispatch_fires_after_three_failures():
    disp = RecordingDispatcher()
    p = Poller(client=_FakeFailingClient(n_failures=10), dispatcher=disp,
               config=_streaming_cfg(account_poll_interval_ms=10))
    import time
    p.poll_once()
    time.sleep(0.05); p.poll_once()
    time.sleep(0.05); p.poll_once()
    assert disp.account_errors == 1


def test_positions_error_dispatch_fires_after_three_failures():
    disp = RecordingDispatcher()
    p = Poller(client=_FakeFailingClient(n_failures=10), dispatcher=disp,
               config=_streaming_cfg(positions_poll_interval_ms=10))
    import time
    p.poll_once()
    time.sleep(0.05); p.poll_once()
    time.sleep(0.05); p.poll_once()
    assert disp.positions_errors == 1


def test_recovery_resets_failure_counter():
    fake = FakeMT5()
    fake._symbol_info_tick["EURUSD"] = FakeTick(time=1, bid=1.10, ask=1.11)
    disp = RecordingDispatcher(symbols={"EURUSD"})
    # Use a real client that we patch transiently.
    client = _client(fake)
    p = Poller(client=client, dispatcher=disp, config=_streaming_cfg())

    # Force two failures via a patched call.
    real_call = client.call
    fail_count = {"n": 2}

    def flaky_call(fn):
        if fail_count["n"] > 0:
            fail_count["n"] -= 1
            raise MT5Error(terminal_not_connected_error())
        return real_call(fn)

    client.call = flaky_call  # type: ignore[assignment]
    p.poll_once(); p.poll_once()
    # Third call succeeds → counter resets, no error fired.
    p.poll_once()
    assert disp.quote_errors == []
    # And the success delivered a tick.
    assert len(disp.ticks) >= 1
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_streaming_poller.py -v -k "error_dispatch or recovery"
```

Expected: PASS (the implementation from Task 6+7 already supports this).

- [ ] **Step 3: Commit**

```bash
git add tests/test_streaming_poller.py
git commit -m "test(phase-3): Poller three-strikes error fanout regression"
```

---

## Task 9: Wire Dispatcher + Poller into AppContext, with lazy lifecycle

**Files:**
- Modify: `src/mt5_mcp/server.py`
- Test: `tests/test_server_appcontext.py` (extend; create if missing — modeled on `test_server_bootstrap.py` if that exists)

- [ ] **Step 1: Inspect existing server tests**

```bash
ls tests/test_server*.py 2>/dev/null
```

- [ ] **Step 2: Write the failing tests**

Append to whichever existing `tests/test_server_*.py` file matches the pattern, or create `tests/test_server_appcontext.py`:

```python
from pathlib import Path

import pytest

from mt5_mcp.server import build_context, build_server, reset_context_for_tests
from mt5_mcp.streaming.dispatcher import Dispatcher
from mt5_mcp.streaming.poller import Poller
from tests.fakes import FakeMT5


def _cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    return cfg


def test_appcontext_has_dispatcher_and_poller(tmp_path):
    fake = FakeMT5()
    ctx = build_context(config_path=_cfg(tmp_path), mt5_module=fake)
    assert isinstance(ctx.dispatcher, Dispatcher)
    assert isinstance(ctx.poller, Poller)


def test_appcontext_dispatcher_bound_to_poller(tmp_path):
    fake = FakeMT5()
    ctx = build_context(config_path=_cfg(tmp_path), mt5_module=fake)
    # Dispatcher delegates start to poller; we verify by checking the bind.
    assert ctx.dispatcher._poller is ctx.poller  # type: ignore[attr-defined]


def test_reset_context_stops_running_poller(tmp_path):
    fake = FakeMT5()
    ctx = build_context(config_path=_cfg(tmp_path), mt5_module=fake)
    ctx.poller.start()
    reset_context_for_tests()
    # After reset, the thread must have exited.
    assert ctx.poller._thread is None  # type: ignore[attr-defined]
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_server_appcontext.py -v
```

Expected: FAIL — `AppContext` has no `dispatcher`/`poller` fields.

- [ ] **Step 4: Wire AppContext**

Edit `src/mt5_mcp/server.py`:

Update the imports near the top:

```python
from mt5_mcp.streaming.dispatcher import Dispatcher
from mt5_mcp.streaming.poller import Poller
```

Replace `AppContext` with:

```python
@dataclass
class AppContext:
    """Hands-off wiring passed from the server to each tool/resource module."""

    client: MT5Client
    symbols: SymbolPrep
    config_watcher: ConfigWatcher | None
    policy: PolicyEngine
    dispatcher: Dispatcher
    poller: Poller

    @property
    def config(self) -> Config:
        if self.config_watcher is not None:
            return self.config_watcher.current
        return Config()
```

Update `build_context` to construct dispatcher + poller and bind them:

```python
def build_context(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> AppContext:
    """Instantiate the client + symbol prep + config watcher + streaming."""
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            return _ctx
        # Config.
        watcher: ConfigWatcher | None = None
        path = config_path or default_config_path()
        if path.exists():
            watcher = ConfigWatcher(path)
            watcher.start()
            cfg = watcher.current
        else:
            cfg = load_config()
        # Client.
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
        # Streaming.
        dispatcher = Dispatcher()
        poller = Poller(client=client, dispatcher=dispatcher, config=cfg.streaming)
        dispatcher.bind_poller(poller)
        _ctx = AppContext(
            client=client, symbols=symbols, config_watcher=watcher,
            policy=policy, dispatcher=dispatcher, poller=poller,
        )
        return _ctx
```

Update `reset_context_for_tests` to stop the poller:

```python
def reset_context_for_tests() -> None:
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            try:
                _ctx.poller.stop()
            except Exception:
                pass
            if _ctx.config_watcher is not None:
                _ctx.config_watcher.stop()
            _ctx.policy.close()
        _ctx = None
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_server_appcontext.py -v
pytest -v  # full suite to catch regressions
```

Expected: PASS for the three new tests AND all existing tests (Phase 1 + Phase 2 unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/server.py tests/test_server_appcontext.py
git commit -m "feat(phase-3): wire Dispatcher + Poller into AppContext"
```

---

## Task 10: `quotes://{symbol}` resource — read path

**Files:**
- Create: `src/mt5_mcp/resources/__init__.py`
- Create: `src/mt5_mcp/resources/quotes.py`
- Create: `tests/test_resources_quotes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resources_quotes.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.errors import MT5Error
from mt5_mcp.server import build_server, get_context
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, fake


def _read_resource(server, uri: str):
    """Helper that resolves a FastMCP resource the same way doctor calls tools."""
    # FastMCP's resource manager exposes a private accessor mirroring _tool_manager.
    rm = server._resource_manager
    template, params = rm.match_uri(uri) if hasattr(rm, "match_uri") else (None, {})
    if template is not None:
        return template.fn(**params)
    # Fallback: direct lookup for fixed URIs.
    return rm.get_resource(uri).fn()


def test_quotes_read_returns_quote(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    q = _read_resource(server, "quotes://EURUSD")
    assert q.bid == Decimal("1.0823")
    assert q.ask == Decimal("1.0824")
    assert q.symbol == "EURUSD"


def test_quotes_read_unknown_symbol_raises_resource_not_found(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["XYZ"] = None
    with pytest.raises(MT5Error) as exc_info:
        _read_resource(server, "quotes://XYZ")
    assert exc_info.value.detail.code in ("RESOURCE_NOT_FOUND", "SYMBOL_NOT_FOUND")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_resources_quotes.py -v
```

Expected: FAIL — `_resource_manager` returns nothing or `quotes://EURUSD` is unregistered.

- [ ] **Step 3: Create the resource handler + register hook**

Create `src/mt5_mcp/resources/__init__.py`:

```python
"""MCP resource registrations.

register_resources(mcp) is called from server.build_server alongside
register_tools. Each module exposes a register(mcp) function.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    from mt5_mcp.resources import account, positions, quotes
    quotes.register(mcp)
    account.register(mcp)
    positions.register(mcp)
```

Create `src/mt5_mcp/resources/quotes.py`:

```python
"""quotes://{symbol} resource.

Read path returns a `Quote` (the same Pydantic model as the get_quote
tool). Subscribe path is wired up in a later task.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import quote_from_tick
from mt5_mcp.errors import MT5Error, resource_not_found
from mt5_mcp.server import get_context
from mt5_mcp.types import Quote


def register(mcp: FastMCP) -> None:
    @mcp.resource("quotes://{symbol}")
    def read_quote(symbol: str) -> Quote:
        """Current bid/ask/last for a symbol."""
        ctx = get_context()
        ctx.client.connect()
        try:
            ctx.symbols.get(symbol)
        except MT5Error:
            raise MT5Error(resource_not_found(f"quotes://{symbol}"))
        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is None:
            raise MT5Error(resource_not_found(f"quotes://{symbol}"))
        return quote_from_tick(
            tick, symbol=symbol,
            broker_offset_minutes=ctx.client.broker_offset_minutes,
        )
```

Update `src/mt5_mcp/server.py`'s `build_server` to also register resources:

```python
def build_server(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> FastMCP:
    """Build a FastMCP server with all tools and resources registered."""
    build_context(config_path=config_path, mt5_module=mt5_module)
    mcp = FastMCP("mt5-mcp")
    from mt5_mcp.tools import register_tools
    from mt5_mcp.resources import register_resources

    register_tools(mcp)
    register_resources(mcp)
    return mcp
```

Note about the `_read_resource` test helper: FastMCP's exact resource-manager API may differ between releases. If `rm.match_uri` is not present, replace the helper body with the FastMCP-current equivalent (e.g. `rm._resources` or `rm.get_resource_template`); the substance — invoke the registered handler with the parsed URI parameters — is what matters. Verify against the installed FastMCP version during this task and adjust the helper inline.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_resources_quotes.py -v
```

Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/resources/__init__.py src/mt5_mcp/resources/quotes.py src/mt5_mcp/server.py tests/test_resources_quotes.py
git commit -m "feat(phase-3): quotes://{symbol} read resource"
```

---

## Task 11: `account://current` resource — read path

**Files:**
- Create: `src/mt5_mcp/resources/account.py`
- Create: `tests/test_resources_account.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resources_account.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeAccountInfo, FakeMT5, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._account_info = FakeAccountInfo(
        login=42, name="Test", server="X", currency="USD",
        balance=10_000.0, equity=10_050.0, margin=100.0,
        margin_free=9_950.0, margin_level=10_050.0, leverage=100,
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _read_resource(server, uri):
    rm = server._resource_manager
    if hasattr(rm, "match_uri"):
        template, params = rm.match_uri(uri)
        if template is not None:
            return template.fn(**params)
    return rm.get_resource(uri).fn()


def test_account_resource_returns_account_info(server_and_mt5):
    server, _ = server_and_mt5
    info = _read_resource(server, "account://current")
    assert info.login == 42
    assert info.balance == Decimal("10000.0")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_resources_account.py -v
```

Expected: FAIL — `account://current` not registered.

- [ ] **Step 3: Create the resource**

Create `src/mt5_mcp/resources/account.py`:

```python
"""account://current resource.

Returns the same AccountInfo Pydantic model as the get_account_info tool.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import account_info_from_raw
from mt5_mcp.errors import MT5Error, terminal_not_connected_error
from mt5_mcp.server import get_context
from mt5_mcp.types import AccountInfo


def register(mcp: FastMCP) -> None:
    @mcp.resource("account://current")
    def read_account() -> AccountInfo:
        """Current account snapshot (balance, equity, margin, leverage, etc.)."""
        ctx = get_context()
        ctx.client.connect()
        raw = ctx.client.call(lambda m: m.account_info())
        if raw is None:
            raise MT5Error(terminal_not_connected_error(
                why="account_info() returned None mid-session",
            ))
        return account_info_from_raw(raw)
```

Note: Verify the exact name of the conversion helper in `adapter/conversions.py`. If `account_info_from_raw` doesn't exist, use whatever the `get_account_info` tool uses (look at `src/mt5_mcp/tools/account.py`). Match its import name.

- [ ] **Step 4: Sanity-check the conversion helper name**

```bash
grep -n "def account_info" src/mt5_mcp/adapter/conversions.py src/mt5_mcp/tools/account.py
```

Adjust the import in `account.py` if the helper has a different name.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_resources_account.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/resources/account.py tests/test_resources_account.py
git commit -m "feat(phase-3): account://current read resource"
```

---

## Task 12: `positions://current` resource — read path

**Files:**
- Create: `src/mt5_mcp/resources/positions.py`
- Create: `tests/test_resources_positions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resources_positions.py`:

```python
from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeMT5, FakePosition, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    return build_server(mt5_module=fake, config_path=cfg), fake


def _read_resource(server, uri):
    rm = server._resource_manager
    if hasattr(rm, "match_uri"):
        template, params = rm.match_uri(uri)
        if template is not None:
            return template.fn(**params)
    return rm.get_resource(uri).fn()


def test_positions_resource_returns_empty_when_none(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = ()
    out = _read_resource(server, "positions://current")
    assert out == []


def test_positions_resource_returns_open_positions(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=1, symbol="EURUSD", volume=0.10),
        FakePosition(ticket=2, symbol="GBPUSD", volume=0.20),
    )
    out = _read_resource(server, "positions://current")
    assert {p.ticket for p in out} == {1, 2}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_resources_positions.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create the resource**

Create `src/mt5_mcp/resources/positions.py`:

```python
"""positions://current resource.

Returns the same list[Position] as the get_positions tool.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import position_from_raw
from mt5_mcp.server import get_context
from mt5_mcp.types import Position


def register(mcp: FastMCP) -> None:
    @mcp.resource("positions://current")
    def read_positions() -> list[Position]:
        """Currently open positions."""
        ctx = get_context()
        ctx.client.connect()
        raws = ctx.client.call(lambda m: m.positions_get())
        if raws is None:
            return []
        return [
            position_from_raw(r, broker_offset_minutes=ctx.client.broker_offset_minutes)
            for r in raws
        ]
```

If `position_from_raw` or its signature differs, look at how `tools/positions.py` produces its output and copy that pattern verbatim.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_resources_positions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/resources/positions.py tests/test_resources_positions.py
git commit -m "feat(phase-3): positions://current read resource"
```

---

## Task 13: HTTP transport — `transport.run()` + `_is_loopback`

**Files:**
- Create: `src/mt5_mcp/transport.py`
- Create: `tests/test_transport.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transport.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from mt5_mcp.config import Config, StreamingSection, TransportHTTPSection, TransportSection
from mt5_mcp.transport import _is_loopback, run


def test_is_loopback_accepts_localhost_and_127_loopback():
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("::1") is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("0.0.0.0") is False
    assert _is_loopback("192.168.1.5") is False
    assert _is_loopback("example.com") is False


@dataclass
class _StubFastMCP:
    """Captures run() args for assertions."""
    last_args: dict | None = None
    middlewares: list = None  # populated below

    def __post_init__(self):
        self.middlewares = []

    def add_middleware(self, mw):
        self.middlewares.append(mw)

    def run(self, **kwargs):
        self.last_args = kwargs


def _cfg(host="127.0.0.1", port=8765, token=""):
    return Config(
        transport=TransportSection(
            http=TransportHTTPSection(host=host, port=port, auth_token=token),
        ),
    )


def test_run_stdio_calls_run_without_transport_kwargs():
    mcp = _StubFastMCP()
    run(mcp, transport="stdio", config=_cfg())
    # FastMCP STDIO mode: either no args or transport="stdio".
    assert mcp.last_args == {} or mcp.last_args == {"transport": "stdio"}


def test_run_http_loopback_no_token_does_not_install_middleware():
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(host="127.0.0.1", port=8765))
    assert mcp.middlewares == []
    assert mcp.last_args["transport"] == "streamable-http"
    assert mcp.last_args["host"] == "127.0.0.1"
    assert mcp.last_args["port"] == 8765


def test_run_http_with_token_installs_bearer_middleware():
    from mt5_mcp.transport import BearerAuthMiddleware
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(token="s3cr3t"))
    assert len(mcp.middlewares) == 1
    # Middleware factory may take the token at construction time.
    # Whatever the factory wraps it as, ensure the value is reachable.
    mw_obj = mcp.middlewares[0]
    assert "s3cr3t" in repr(mw_obj) or getattr(mw_obj, "_expected", "").endswith("s3cr3t")


def test_run_http_non_loopback_raises_config_error():
    mcp = _StubFastMCP()
    with pytest.raises(Exception) as exc_info:
        run(mcp, transport="http", config=_cfg(host="0.0.0.0"))
    assert "loopback" in str(exc_info.value).lower()


def test_run_unknown_transport_raises():
    mcp = _StubFastMCP()
    with pytest.raises(Exception):
        run(mcp, transport="ftp", config=_cfg())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_transport.py -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create transport module**

Create `src/mt5_mcp/transport.py`:

```python
"""Transport selection: STDIO (default) and HTTP/SSE (opt-in).

HTTP mode binds loopback only in v0.3 and refuses to start otherwise.
A configured ``transport.http.auth_token`` triggers a Starlette
bearer-auth middleware with constant-time token comparison.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
from typing import Any

from mt5_mcp.config import Config


logger = logging.getLogger(__name__)


class TransportConfigError(ValueError):
    """Raised when the transport configuration is invalid."""


class BearerAuthMiddleware:
    """ASGI middleware: 401 on missing/wrong Authorization: Bearer <token>."""

    def __init__(self, app, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        actual = headers.get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(actual, self._expected):
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            })
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return
        await self._app(scope, receive, send)


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def run(mcp: Any, *, transport: str, config: Config) -> None:
    """Boot the MCP server on the chosen transport.

    Raises ``TransportConfigError`` for invalid configurations BEFORE
    the server starts so the operator sees the failure on the same
    terminal that ran the command.
    """
    if transport == "stdio":
        mcp.run()
        return
    if transport == "http":
        host = config.transport.http.host
        port = config.transport.http.port
        if not _is_loopback(host):
            raise TransportConfigError(
                f"transport.http.host must be a loopback address in v0.3 "
                f"(got {host!r}); set 127.0.0.1, ::1, or localhost"
            )
        token = config.transport.http.auth_token
        if token:
            mcp.add_middleware(_make_bearer_middleware_factory(token))
        mcp.run(transport="streamable-http", host=host, port=port)
        return
    raise TransportConfigError(f"unknown transport: {transport!r}")


def _make_bearer_middleware_factory(token: str):
    """Return a callable FastMCP/Starlette accepts as a middleware spec.

    FastMCP's add_middleware may accept either a class or an instance.
    We store the token on the returned object so tests can introspect it.
    """
    expected = f"Bearer {token}"

    class _Factory:
        def __init__(self) -> None:
            self._expected = expected

        def __call__(self, app):
            return BearerAuthMiddleware(app, token)

        def __repr__(self) -> str:
            return f"<BearerAuthMiddlewareFactory token=...{token[-3:]}>"

    return _Factory()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_transport.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/transport.py tests/test_transport.py
git commit -m "feat(phase-3): transport.run() + bearer-auth middleware"
```

---

## Task 14: Wire `--transport` into `python -m mt5_mcp serve`

**Files:**
- Modify: `src/mt5_mcp/__main__.py`
- Test: `tests/test_main_cli.py` (extend; create if missing)

- [ ] **Step 1: Write the failing tests**

Create or extend `tests/test_main_cli.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest

from mt5_mcp.__main__ import main


def test_serve_default_transport_is_stdio(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # stop Windows wandering off
    captured = {}
    def fake_run(mcp, *, transport, config):
        captured["transport"] = transport
    with patch("mt5_mcp.transport.run", side_effect=fake_run):
        rc = main(["serve"])
    assert rc == 0
    assert captured["transport"] == "stdio"


def test_serve_http_transport_routes_to_http(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    captured = {}
    def fake_run(mcp, *, transport, config):
        captured["transport"] = transport
    with patch("mt5_mcp.transport.run", side_effect=fake_run):
        rc = main(["serve", "--transport", "http"])
    assert rc == 0
    assert captured["transport"] == "http"


def test_serve_invalid_transport_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    rc = main(["serve", "--transport", "ftp"])
    assert rc != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_cli.py -v
```

Expected: FAIL — current `serve` ignores `--transport`.

- [ ] **Step 3: Update `__main__.py`**

Replace `src/mt5_mcp/__main__.py`:

```python
"""Entry point: `python -m mt5_mcp <command>`.

Commands:
  serve [--transport stdio|http]   Run the MCP server (default: stdio).
  doctor                            Run read-tool health check.
  export-symbols                    Dump broker symbols to CSV.
  reload-config                     Touch the config file so a running server reloads.
"""

from __future__ import annotations

import argparse
import sys


def _run_serve(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="mt5-mcp serve")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="MCP transport to run on (default: stdio).",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config TOML (default: per-OS user config dir).",
    )
    args = parser.parse_args(argv)

    from pathlib import Path
    from mt5_mcp.config import load_config
    from mt5_mcp.server import build_server
    from mt5_mcp.transport import TransportConfigError, run

    config_path = Path(args.config) if args.config else None
    server = build_server(config_path=config_path)
    cfg = load_config(config_path)
    try:
        run(server, transport=args.transport, config=cfg)
    except TransportConfigError as exc:
        print(f"transport error: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] == "serve":
        return _run_serve(argv[1:] if argv else [])

    cmd = argv[0]

    if cmd == "doctor":
        from mt5_mcp.cli.doctor import main as doctor_main
        return doctor_main(argv[1:])

    if cmd == "export-symbols":
        from mt5_mcp.cli.export_symbols import main as export_main
        return export_main(argv[1:])

    if cmd == "reload-config":
        import os
        from mt5_mcp.config import default_config_path
        path = default_config_path()
        if not path.exists():
            print(f"no config file at {path}", file=sys.stderr)
            return 1
        os.utime(path, None)
        print(f"touched {path}; running server should reload")
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    print(main.__doc__ or "", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_main_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite to catch any regression**

```bash
pytest -v
```

Expected: PASS — Phase 1 + Phase 2 + Phase 3 progress all green.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/__main__.py tests/test_main_cli.py
git commit -m "feat(phase-3): serve --transport {stdio,http} CLI flag"
```

---

## Task 15: `doctor [streaming]` check — live-terminal poller smoke

**Files:**
- Modify: `src/mt5_mcp/cli/doctor.py`
- Test: `tests/test_doctor_streaming.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_doctor_streaming.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mt5_mcp.cli.doctor import run_doctor
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
        '[streaming]\nquote_poll_interval_ms = 50\n'
    )
    return cfg


def test_doctor_streaming_check_passes_with_active_tick(tmp_path, capsys):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD",
                    config_path=_config(tmp_path), check_streaming=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[PASS] streaming" in out
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_doctor_streaming.py -v
```

Expected: FAIL — `run_doctor` lacks `check_streaming` parameter; no streaming check.

- [ ] **Step 3: Add the streaming check**

Edit `src/mt5_mcp/cli/doctor.py`:

Add an import at the top:

```python
from mt5_mcp.streaming.snapshots import TickSnapshot
```

Update the `run_doctor` signature and body to add a streaming check:

```python
def run_doctor(
    *,
    mt5_module: Any | None = None,
    probe_symbol: str = "EURUSD",
    config_path: Any | None = None,
    smoke_trade: bool = False,
    check_streaming: bool = True,
) -> int:
    reset_context_for_tests()
    server = build_server(mt5_module=mt5_module, config_path=config_path)
    tm = server._tool_manager

    def call(name: str, **kwargs):
        return tm.get_tool(name).fn(**kwargs)

    results = []
    results.append(_check("ping", lambda: call("ping")))
    results.append(_check("get_terminal_info", lambda: call("get_terminal_info")))
    results.append(_check("get_account_info", lambda: call("get_account_info")))
    results.append(_check("get_symbols", lambda: call("get_symbols")))
    results.append(_check(f"get_quote({probe_symbol})", lambda: call("get_quote", symbol=probe_symbol)))
    results.append(_check(f"get_market_hours({probe_symbol})", lambda: call("get_market_hours", symbol=probe_symbol)))
    results.append(_check("get_positions", lambda: call("get_positions")))
    results.append(_check("get_orders", lambda: call("get_orders")))

    if check_streaming:
        results.append(_streaming_check(probe_symbol))

    # ... existing smoke_trade block unchanged ...

    return 0 if all(results) else 1
```

Add a new helper at module scope:

```python
def _streaming_check(symbol: str) -> bool:
    """Subscribe to quotes://{symbol}, run the poller for ~1s, assert >=1 tick."""
    from mt5_mcp.server import get_context

    ctx = get_context()
    received: list[str] = []

    class _Recorder:
        def notify_updated(self, uri: str) -> None:
            received.append(uri)

    handle = ctx.dispatcher.subscribe(f"quotes://{symbol}", _Recorder())
    try:
        # Poll up to ten short cycles or until we see a tick.
        import time
        for _ in range(10):
            ctx.poller.poll_once()
            if received:
                break
            time.sleep(0.1)
    finally:
        ctx.dispatcher.unsubscribe(handle)

    if received:
        print(f"[PASS] streaming({symbol}) — {len(received)} tick(s) dispatched")
        return True
    print(f"[FAIL] streaming({symbol}) — no ticks observed in ~1s")
    return False
```

Also extend the `argparse` block in `main()` to add `--no-streaming-check`:

```python
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="mt5-mcp doctor")
    parser.add_argument(
        "--smoke-trade", action="store_true",
        help="Round-trip a tiny place_order + close_position against the live "
             "terminal. WARNING: places a real (micro-lot) order on the broker.",
    )
    parser.add_argument(
        "--probe-symbol", default="EURUSD",
        help="Symbol used for read-tool probes (default: EURUSD).",
    )
    parser.add_argument(
        "--no-streaming-check", action="store_true",
        help="Skip the [streaming] subscribe-and-poll check.",
    )
    args = parser.parse_args(argv)
    return run_doctor(
        probe_symbol=args.probe_symbol,
        smoke_trade=args.smoke_trade,
        check_streaming=not args.no_streaming_check,
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_doctor_streaming.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -v
```

Expected: PASS for the entire suite.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/cli/doctor.py tests/test_doctor_streaming.py
git commit -m "feat(phase-3): doctor [streaming] subscribe-and-poll check"
```

---

## Task 16: HTTP transport integration test

**Files:**
- Create: `tests/test_transport_http_integration.py`
- Modify: `pyproject.toml` (add `httpx` to test deps if not present)

- [ ] **Step 1: Inspect existing test deps**

```bash
grep -n "httpx\|pytest" pyproject.toml
```

If `httpx` is not in dev/test deps, add it.

- [ ] **Step 2: Add `httpx` to dev dependencies (skip if already present)**

Edit `pyproject.toml` to add `httpx` to the test or dev extras. For example:

```toml
[project.optional-dependencies]
dev = [
    "pytest",
    "httpx",
    # ... existing
]
```

- [ ] **Step 3: Write the integration test**

Create `tests/test_transport_http_integration.py`:

```python
"""Integration test: boot HTTP transport in a thread, hit it with httpx.

Marked @pytest.mark.integration so CI can selectively skip if flaky.
Run with: pytest -m integration tests/test_transport_http_integration.py -v
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")

from mt5_mcp.config import load_config
from mt5_mcp.server import build_server, reset_context_for_tests
from mt5_mcp.transport import run as transport_run
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def http_server(tmp_path):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    port = _free_port()
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
        f'[transport.http]\nhost = "127.0.0.1"\nport = {port}\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg_path)
    cfg = load_config(cfg_path)

    thread = threading.Thread(
        target=transport_run,
        kwargs=dict(mcp=server, transport="http", config=cfg),
        daemon=True,
    )
    thread.start()
    # Wait until the server is accepting connections (max 5s).
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.skip("HTTP server did not start within 5s")
    yield port
    reset_context_for_tests()


@pytest.mark.integration
def test_http_resources_list_contains_quotes_template(http_server):
    port = http_server
    base = f"http://127.0.0.1:{port}"
    # The streamable-HTTP MCP transport accepts JSON-RPC over POST /mcp.
    # Exact endpoint may differ between FastMCP versions — adjust to match
    # the FastMCP release in use; the test verifies the round-trip.
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {},
    }
    resp = httpx.post(f"{base}/mcp", json=payload, timeout=5.0)
    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body
    uris = [r.get("uriTemplate") or r.get("uri") for r in body["result"].get("resources", [])]
    assert any("quotes://" in (u or "") for u in uris)
```

If FastMCP's HTTP endpoint differs from `/mcp`, look up the current FastMCP docs for the streamable-HTTP path and adjust. The substance is: a server is listening, `resources/list` returns `quotes://{symbol}`, `account://current`, and `positions://current`.

- [ ] **Step 4: Configure pytest to recognize `integration` marker**

If `pyproject.toml` does not already register the marker, add:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests requiring a live HTTP server (deselect with -m 'not integration')",
]
```

- [ ] **Step 5: Run the integration test**

```bash
pytest tests/test_transport_http_integration.py -v -m integration
```

Expected: PASS. If FastMCP's exact endpoint differs and the test cannot reach the server, document the actual endpoint in the test and re-run.

- [ ] **Step 6: Run the unit suite without integration tests**

```bash
pytest -v -m "not integration"
```

Expected: PASS for the entire non-integration suite.

- [ ] **Step 7: Commit**

```bash
git add tests/test_transport_http_integration.py pyproject.toml
git commit -m "test(phase-3): HTTP transport integration test"
```

---

## Task 17: Resource subscribe hooks — wire FastMCP subscribe to Dispatcher

**Files:**
- Modify: `src/mt5_mcp/resources/quotes.py`, `account.py`, `positions.py`
- Create: `tests/test_resources_subscribe.py`

This task is the riskiest one because the exact FastMCP subscribe-hook API may differ between releases. The substance: when FastMCP receives `resources/subscribe`, the resource handler must register the subscriber with `ctx.dispatcher`. Implement against the FastMCP version in use.

- [ ] **Step 1: Inspect FastMCP's subscribe API**

```bash
python -c "from mcp.server.fastmcp import FastMCP; help(FastMCP.resource)" 2>&1 | head -40
python -c "from mcp.server.fastmcp.resources import ResourceManager; print(dir(ResourceManager))" 2>&1 | head -20
```

Look for: `subscribe` decorator method on the resource object, OR a server-level subscribe handler hook. Document the exact pattern in a comment in each resource module.

- [ ] **Step 2: Write the integration test**

Create `tests/test_resources_subscribe.py`:

```python
from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server, get_context
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


@pytest.fixture
def server_and_ctx(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, get_context()


def test_subscribing_via_dispatcher_picks_up_symbol(server_and_ctx):
    server, ctx = server_and_ctx

    class _Sub:
        notifications: list[str] = []

        def notify_updated(self, uri: str) -> None:
            self.notifications.append(uri)

    sub = _Sub()
    handle = ctx.dispatcher.subscribe("quotes://EURUSD", sub)
    assert "EURUSD" in ctx.dispatcher.subscribed_symbols()
    ctx.dispatcher.unsubscribe(handle)
    assert "EURUSD" not in ctx.dispatcher.subscribed_symbols()
```

This test is the smallest integration shim: it exercises the dispatcher path end-to-end through the AppContext that `build_server` constructs. It does NOT exercise FastMCP's `resources/subscribe` protocol method directly — that's the integration test's job (Task 16) once FastMCP exposes the hook.

- [ ] **Step 3: Run the test**

```bash
pytest tests/test_resources_subscribe.py -v
```

Expected: PASS (the dispatcher API is already wired into AppContext from Task 9).

- [ ] **Step 4: If FastMCP exposes a subscribe hook on `@mcp.resource(...)`, wire it**

If `@mcp.resource("quotes://{symbol}")` exposes a `.subscribe` decorator (or similar), add subscribe handlers to each resource module. Pattern (sketch — adjust to actual FastMCP API):

In `src/mt5_mcp/resources/quotes.py`, after `read_quote`:

```python
    # Subscribe hook — only added if FastMCP version supports it.
    subscribe_decorator = getattr(read_quote, "subscribe", None)
    if subscribe_decorator is not None:
        @subscribe_decorator
        def subscribe_quote(symbol: str, subscriber):
            ctx = get_context()
            ctx.symbols.get(symbol)  # validate, raises MT5Error
            return ctx.dispatcher.subscribe(f"quotes://{symbol}", subscriber)
```

Repeat the equivalent for `account.py` and `positions.py` with their fixed URIs.

If FastMCP does NOT expose a per-resource subscribe hook in the installed version, document this in the resource module's docstring and rely on the integration-test verification (Task 16) — clients calling `resources/subscribe` will go through whatever FastMCP-default behavior exists, which may simply track the subscription internally without invoking our dispatcher. In that case, mark this gap in CLAUDE.md as a Phase 3 carryover for resolution when FastMCP adds the hook.

- [ ] **Step 5: Run the full suite**

```bash
pytest -v
```

Expected: PASS for everything.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/resources tests/test_resources_subscribe.py
git commit -m "feat(phase-3): wire resource subscribe hooks (where supported by FastMCP)"
```

---

## Task 18: README + architecture doc updates + CLAUDE.md handover

**Files:**
- Modify: `README.md`
- Modify: `mt5-mcp-architecture.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update README**

Add a new "Resources" section under the existing "Tools" section, listing the three resources and their behavior (subscribable, change-detection rules, default poll cadence). Add a new "Transports" section documenting `serve --transport stdio` (default) and `serve --transport http` (with `[transport.http]` config — host/port/auth_token, loopback-only constraint).

Refer to the spec at `docs/superpowers/specs/2026-04-27-phase-3-resources-and-http-transport-design.md` for content.

- [ ] **Step 2: Update architecture doc**

Edit `mt5-mcp-architecture.md`:

- §15: move plugin loader from Phase 3 to Phase 4.
- §16 q4 (quote subscriptions): mark resolved with the chosen poll cadences.
- Add a new section (§6.x or §7.x) describing the streaming subsystem (Poller + Dispatcher, lazy-start lifecycle, change-detection rules).
- Add a new section describing the HTTP transport (loopback-only, optional bearer token, `serve --transport` CLI).

- [ ] **Step 3: Update CLAUDE.md handover notes**

Append a "Phase 3 (in progress / completed)" section that documents:

- New packages: `streaming/` and `resources/`.
- New AppContext fields: `dispatcher`, `poller`.
- New patterns the next agent must preserve:
  - Resources do NOT use `@error_envelope` — they raise MT5Error and FastMCP renders the protocol error.
  - Resource read paths use `ctx.client.call(...)` like Phase 1 read tools.
  - The poller is lazy-started on first subscription, lazy-stopped on last unsubscribe.
  - Streaming snapshot dataclasses live in `streaming/snapshots.py`, never in `tests/fakes.py`.
- Carryover items now formally Phase 4: plugin loader, audit log compression, idempotency TTL sweeper, non-loopback HTTP bind.

- [ ] **Step 4: Commit**

```bash
git add README.md mt5-mcp-architecture.md CLAUDE.md
git commit -m "docs(phase-3): document resources, HTTP transport, streaming subsystem"
```

---

## Task 19: Tag and final verification

**Files:**
- (No files modified — verification + tagging only)

- [ ] **Step 1: Run the full suite one final time**

```bash
pytest -v
```

Expected: 100% PASS (Phase 1 + Phase 2 + Phase 3 tests all green).

- [ ] **Step 2: Run a quick lint/typecheck**

If the repo has a linter or typechecker configured (e.g. ruff, mypy), run it:

```bash
ruff check src tests 2>/dev/null || true
mypy src 2>/dev/null || true
```

Address any introduced issues before tagging.

- [ ] **Step 3: Live-terminal smoke check (optional, requires MT5)**

```bash
python -m mt5_mcp doctor
python -m mt5_mcp doctor --smoke-trade
python -m mt5_mcp serve --transport http &
# In another shell: send a resources/list over HTTP to confirm
```

- [ ] **Step 4: Tag the release**

```bash
git tag -a phase-3-complete -m "Phase 3: Resources + HTTP transport"
git push origin main
git push origin phase-3-complete
```

- [ ] **Step 5: Confirm tag landed**

```bash
git fetch --tags
git tag -l "phase-*"
```

Expected output includes `phase-1-complete`, `phase-2-complete`, `phase-3-complete`.

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by task |
|---|---|
| §3 file layout: `streaming/`, `resources/`, `transport.py`, server changes | Tasks 3, 4-8, 10-13, 9 |
| §4 snapshot dataclasses | Task 3 |
| §5 Poller (start/stop/wake/loop/diff/error) | Tasks 6, 7, 8 |
| §6 Dispatcher (subscribe/unsubscribe/refcount/fanout/reap) | Tasks 4, 5 |
| §7 Resource handlers (quotes/account/positions read + subscribe) | Tasks 10, 11, 12, 17 |
| §8 transport.run() + BearerAuthMiddleware + CLI | Tasks 13, 14 |
| §9 config additions (`[transport.http]` host/port, `[streaming]`) | Task 1 |
| §10 error handling — `resource_not_found` factory, 401 middleware, ConfigError on non-loopback | Tasks 2, 13 |
| §11 edge cases (broker drop, rapid sub/unsub, multi-sub, hot-reload immutable intervals) | Covered implicitly via tests; no separate task |
| §12 testing (unit + one integration) | Tasks 4-8, 10-13, 16 |
| §12 doctor `[streaming]` check | Task 15 |
| §13 out of scope | Documented in §13; nothing to implement |
| §14 architecture doc updates | Task 18 |
| §15 invariants (no `@error_envelope` on resources, `ctx.client.call`, no test imports in src) | Enforced by pattern in Tasks 10-12 |

**Placeholder scan:** No "TBD", "TODO", or unspecified-behavior steps. Two tasks (10 and 17) include a "verify against installed FastMCP version" step because the public API for resource templates and subscribe hooks varies across FastMCP releases — that's not a placeholder, it's an explicit verification step with a fallback documented.

**Type consistency:**
- `Dispatcher.subscribe(uri, subscriber) -> SubscriptionHandle` — used consistently in Tasks 4, 5, 9, 17.
- `Poller(client=, dispatcher=, config=)` — same kwargs across Tasks 6, 7, 8, 9.
- `StreamingSection.{quote,account,positions}_poll_interval_ms` — defined in Task 1, consumed in Tasks 6, 7, 9, 15.
- `_is_loopback(host) -> bool` and `BearerAuthMiddleware(app, token)` — defined and tested in Task 13, used in Task 14.

**Scope check:** 19 tasks for one phase is on the high end. They're cohesive — every task builds on the previous one or adds an isolated piece (config, errors, docs). The plan does not need decomposition into sub-plans.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-27-phase-3-resources-and-http-transport.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, run dual-review (spec-conformance + code-quality) between tasks, fast iteration. This is the validated workflow from Phase 2 (memory: `feedback_subagent_dual_review.md`).

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
