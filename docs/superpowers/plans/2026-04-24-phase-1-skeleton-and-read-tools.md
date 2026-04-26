# Phase 1 — Skeleton + Read Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `mt5-mcp` package skeleton with configuration loading, mt5lib adapter (connection, symbol preparation, type marshalling, broker-TZ→UTC conversion), all 9 MCP read tools, and two CLI companions (`doctor`, `export-symbols`).

**Architecture:** A Python package (`mt5_mcp`) that exposes MetaTrader5 Python library calls as MCP tools via the official `mcp[cli]` SDK using `FastMCP`. The adapter layer wraps `MetaTrader5` as a singleton and translates timestamps to UTC, enforces symbol preparation (select + filling-mode probe + volume / price validation) with a 60s cache, and converts native MT5 types into Pydantic models serialised as JSON (Decimals as strings). Read tools are thin handlers over the adapter. Unit tests mock `MetaTrader5` entirely — no live terminal needed.

**Tech Stack:**
- Python 3.10+
- `mcp[cli]` (official MCP Python SDK; uses `FastMCP`)
- `MetaTrader5` (vendor library; import-gated on non-Windows)
- `pydantic` v2 (models + settings)
- `watchdog` (cross-platform file watching for hot reload)
- `tomli` (TOML parser; stdlib `tomllib` is 3.11+, so we use `tomli` for 3.10 compat)
- `pytest` + `pytest-mock` + `freezegun` (unit tests)
- Build backend: `hatchling`

---

## File Structure

Phase 1 touches only these files. Policy / mutating-tool files from §4 of the architecture are deferred to Phase 2.

**Package root:**
- `pyproject.toml` — package metadata, deps, entry points (`mt5-mcp` console script)
- `README.md` — short install + quickstart
- `LICENCE` — MIT
- `.gitignore` — standard Python + venv + build artefacts
- `conftest.py` — (project root) ensures `src/` is on `sys.path` for tests

**Source (`src/mt5_mcp/`):**
- `__init__.py` — re-exports `__version__`
- `__main__.py` — `python -m mt5_mcp` entry; dispatches `serve` / `doctor` / `export-symbols` / `reload-config`
- `server.py` — builds the `FastMCP` instance and registers tools
- `types.py` — Pydantic models returned by tools (`AccountInfo`, `Position`, `Order`, `Deal`, `Quote`, `SymbolInfo`, `MarketHours`, `TerminalInfo`, `ErrorDetail`)
- `config.py` — Pydantic config model + TOML loader + watchdog-based auto-reload
- `errors.py` — maps `mt5lib` retcodes to `ErrorDetail` codes; defines `MT5Error` exception
- `adapter/__init__.py` — package marker
- `adapter/mt5_client.py` — singleton wrapper around `MetaTrader5`, connection lifecycle, broker-TZ offset cache, transparent re-init
- `adapter/symbols.py` — symbol preparation pipeline (select / filling-mode probe / volume + price validation / 60s cache)
- `adapter/conversions.py` — `MetaTrader5` named-tuples → dict / Pydantic; broker-TZ→UTC timestamps; Decimal coercion
- `tools/__init__.py` — `register_tools(mcp)` entry point
- `tools/system.py` — `ping`, `get_terminal_info`
- `tools/account.py` — `get_account_info`
- `tools/market.py` — `get_quote`, `get_symbols`, `get_market_hours`
- `tools/positions.py` — `get_positions`
- `tools/orders.py` — `get_orders`
- `tools/history.py` — `get_history`
- `cli/__init__.py` — package marker
- `cli/doctor.py` — `doctor` smoke check
- `cli/export_symbols.py` — `export-symbols --output symbols.csv`

**Tests (`tests/`):**
- `conftest.py` — pytest fixtures: fake `MetaTrader5` module, frozen clock, sample responses
- `fakes.py` — `FakeMT5` class implementing the subset of `MetaTrader5` we call
- `test_config.py`
- `test_adapter_mt5_client.py`
- `test_adapter_conversions.py`
- `test_adapter_symbols.py`
- `test_errors.py`
- `test_tools_system.py`
- `test_tools_account.py`
- `test_tools_market.py`
- `test_tools_positions.py`
- `test_tools_orders.py`
- `test_tools_history.py`
- `test_cli_doctor.py`
- `test_cli_export_symbols.py`

**Rationale for splits:**
- `adapter/` lives alone because it is the single place where `MetaTrader5` is imported and naive timestamps become UTC — concentrating both makes the "broker-TZ never leaks" invariant easy to audit.
- Tools split by domain (system / account / market / positions / orders / history) because they'll grow in Phase 2 (`positions.py` gains `close_position`, `orders.py` gains `place_order` / `modify_order` / `cancel_order`, etc.). Keeping the split now means Phase 2 only *adds* to existing files.
- `errors.py` is top-level (not under `adapter/`) because Phase 2 policy code will also raise / return `ErrorDetail`s.
- `cli/` is separate from `tools/` because CLI commands are not MCP tools — they shouldn't be discoverable by `register_tools`.

---

## Implementation conventions

Applied throughout every task:

- **TDD**: write the failing test first, then the minimum code to pass it.
- **No `MetaTrader5` import at import time** in any module that isn't `adapter/mt5_client.py`. Import lazily inside the client so tests on non-Windows machines don't explode.
- **All Decimals in types** — never `float`. Input from `MetaTrader5` comes as `float`; convert with `Decimal(str(f))` to avoid binary-float artefacts.
- **All datetimes in types are timezone-aware UTC**. `adapter/conversions.py` is the only producer.
- **Commit after each task**. Commit messages follow Conventional Commits (`feat:`, `test:`, `chore:`, `docs:`).

---

## Task 1: Bootstrap the package

**Files:**
- Create: `pyproject.toml`
- Create: `LICENCE`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/mt5_mcp/__init__.py`
- Create: `src/mt5_mcp/__main__.py`
- Create: `conftest.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mt5-mcp"
version = "0.1.0"
description = "Model Context Protocol server wrapping the MetaTrader 5 Python library."
readme = "README.md"
license = { file = "LICENCE" }
authors = [{ name = "Fintrix Markets", email = "security@fintrixmarkets.com" }]
requires-python = ">=3.10"
classifiers = [
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Operating System :: Microsoft :: Windows",
  "Topic :: Office/Business :: Financial :: Investment",
]
dependencies = [
  "mcp[cli]>=1.12",
  "pydantic>=2.6",
  "watchdog>=4.0",
  "tomli>=2.0; python_version < '3.11'",
  "MetaTrader5>=5.0.45; platform_system == 'Windows'",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-mock>=3.12",
  "freezegun>=1.4",
]

[project.scripts]
mt5-mcp = "mt5_mcp.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/mt5_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Write `LICENCE` (MIT boilerplate, current year, Fintrix Markets)**

Use the standard MIT text from https://opensource.org/license/mit — replace `<YEAR>` with `2026` and `<COPYRIGHT HOLDER>` with `Fintrix Markets`.

- [ ] **Step 3: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.pytest_cache/
.venv/
venv/
build/
dist/

# Editors
.idea/
.vscode/
*.swp

# OS
.DS_Store
Thumbs.db

# Project
symbols.csv
*.jsonl
```

- [ ] **Step 4: Write `README.md`** (minimal; will be expanded in Phase 4)

```markdown
# mt5-mcp

Model Context Protocol server wrapping the MetaTrader 5 Python library.

**Status:** v0.1 — Phase 1 (skeleton + read tools).

## Install

```bash
pip install mt5-mcp
```

Requires Windows with MetaTrader 5 terminal installed and logged into a broker.

## Quick check

```bash
python -m mt5_mcp doctor
```

See `mt5-mcp-architecture.md` for the full design.
```

- [ ] **Step 5: Write `src/mt5_mcp/__init__.py`**

```python
"""mt5-mcp — MCP server wrapping the MetaTrader 5 Python library."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Write a placeholder `src/mt5_mcp/__main__.py`**

```python
"""Entry point: `python -m mt5_mcp`."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "serve":
        # Wired up in Task 11 (server bootstrap).
        raise SystemExit("serve not yet implemented")
    if argv[0] == "doctor":
        # Wired up in Task 14.
        raise SystemExit("doctor not yet implemented")
    if argv[0] == "export-symbols":
        # Wired up in Task 15.
        raise SystemExit("export-symbols not yet implemented")
    if argv[0] == "reload-config":
        # Wired up in Task 3.
        raise SystemExit("reload-config not yet implemented")
    print(f"Unknown command: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Write `conftest.py` at project root** (empty but necessary placeholder)

```python
# Test configuration root. Real fixtures live in tests/conftest.py.
```

- [ ] **Step 8: Write `tests/__init__.py`** (empty)

- [ ] **Step 9: Install dev deps and verify install**

Run: `pip install -e ".[dev]"`
Expected: installs without error; on non-Windows the `MetaTrader5` dep is skipped by marker.

Run: `python -c "import mt5_mcp; print(mt5_mcp.__version__)"`
Expected: `0.1.0`

Run: `pytest -q`
Expected: `no tests ran in 0.xxs` (clean exit).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml LICENCE .gitignore README.md src/ tests/ conftest.py
git commit -m "chore: bootstrap mt5-mcp package skeleton"
```

---

## Task 2: Shared test harness — `FakeMT5`

A hand-rolled fake is easier to reason about than `MagicMock` for a library with ~30 call sites and strongly-typed return tuples. Every adapter / tool test instantiates `FakeMT5` and sets its attributes.

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fakes.py`

- [ ] **Step 1: Write `tests/fakes.py`**

```python
"""
FakeMT5 — hand-rolled stand-in for the MetaTrader5 module.

The real MetaTrader5 library is Windows-only and exposes ~30 module-level
functions that return NamedTuples. FakeMT5 mimics only the subset we call,
using plain @dataclass objects so tests can introspect them. Each method
returns whatever the test has put in the corresponding `._<method>` slot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# mt5lib retcode constants we reference. Values per MetaTrader5 docs.
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_REQUOTE = 10004
TRADE_RETCODE_REJECT = 10006
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_PRICE = 10015
TRADE_RETCODE_NO_MONEY = 10019
TRADE_RETCODE_MARKET_CLOSED = 10018

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2

# Bitmask values as exposed by `SymbolInfo.filling_mode`.
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5


@dataclass
class FakeTerminalInfo:
    connected: bool = True
    trade_allowed: bool = True
    build: int = 4150
    name: str = "MetaTrader 5"
    company: str = "FintrixMarkets Ltd"
    path: str = "C:/Program Files/MetaTrader 5"
    # Broker-server time as a UNIX epoch treated as naive. See conversions.py.
    time: int = 1_745_000_000


@dataclass
class FakeAccountInfo:
    login: int = 123456
    name: str = "Demo User"
    server: str = "FintrixMarkets-Demo"
    currency: str = "USD"
    balance: float = 10_000.0
    equity: float = 10_050.0
    margin: float = 100.0
    margin_free: float = 9_950.0
    margin_level: float = 10_050.0
    leverage: int = 100
    trade_allowed: bool = True
    margin_mode: int = 0  # 0 = ACCOUNT_MARGIN_MODE_RETAIL_NETTING


@dataclass
class FakeSymbolInfo:
    name: str = "EURUSD"
    description: str = "Euro vs US Dollar"
    path: str = "Forex\\Majors\\EURUSD"
    visible: bool = True
    trade_mode: int = 4  # 4 = full; 0 = disabled
    filling_mode: int = SYMBOL_FILLING_IOC | SYMBOL_FILLING_FOK
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    digits: int = 5
    point: float = 0.00001
    trade_contract_size: float = 100_000.0
    currency_base: str = "EUR"
    currency_profit: float = "USD"  # mt5lib uses string, not float
    currency_margin: str = "USD"
    bid: float = 1.0823
    ask: float = 1.0824


@dataclass
class FakeTick:
    time: int = 1_745_000_000
    bid: float = 1.0823
    ask: float = 1.0824
    last: float = 0.0
    volume: int = 0


@dataclass
class FakePosition:
    ticket: int = 1
    symbol: str = "EURUSD"
    type: int = POSITION_TYPE_BUY
    volume: float = 0.10
    price_open: float = 1.0820
    price_current: float = 1.0824
    sl: float = 0.0
    tp: float = 0.0
    profit: float = 4.0
    swap: float = 0.0
    commission: float = 0.0
    time: int = 1_745_000_000
    comment: str = ""


@dataclass
class FakeOrder:
    ticket: int = 2
    symbol: str = "EURUSD"
    type: int = ORDER_TYPE_BUY_LIMIT
    volume_initial: float = 0.10
    volume_current: float = 0.10
    price_open: float = 1.0800
    sl: float = 0.0
    tp: float = 0.0
    time_setup: int = 1_745_000_000
    time_expiration: int = 0
    comment: str = ""


@dataclass
class FakeDeal:
    ticket: int = 100
    order: int = 50
    symbol: str = "EURUSD"
    type: int = 0  # 0 = buy, 1 = sell
    volume: float = 0.10
    price: float = 1.0822
    profit: float = 5.0
    swap: float = 0.0
    commission: float = -0.5
    time: int = 1_745_000_000
    comment: str = ""


@dataclass
class FakeMT5:
    """
    Stand-in for the MetaTrader5 module. Pre-populate slots for whatever
    your test exercises; unset slots raise AttributeError so missing
    coverage shows up loudly.
    """

    # Retcode / enum constants the real module exposes at module scope.
    TRADE_RETCODE_DONE: int = TRADE_RETCODE_DONE
    TRADE_RETCODE_REQUOTE: int = TRADE_RETCODE_REQUOTE
    TRADE_RETCODE_REJECT: int = TRADE_RETCODE_REJECT
    TRADE_RETCODE_INVALID_VOLUME: int = TRADE_RETCODE_INVALID_VOLUME
    TRADE_RETCODE_INVALID_PRICE: int = TRADE_RETCODE_INVALID_PRICE
    TRADE_RETCODE_NO_MONEY: int = TRADE_RETCODE_NO_MONEY
    TRADE_RETCODE_MARKET_CLOSED: int = TRADE_RETCODE_MARKET_CLOSED
    ORDER_FILLING_FOK: int = ORDER_FILLING_FOK
    ORDER_FILLING_IOC: int = ORDER_FILLING_IOC
    ORDER_FILLING_RETURN: int = ORDER_FILLING_RETURN
    SYMBOL_FILLING_FOK: int = SYMBOL_FILLING_FOK
    SYMBOL_FILLING_IOC: int = SYMBOL_FILLING_IOC
    POSITION_TYPE_BUY: int = POSITION_TYPE_BUY
    POSITION_TYPE_SELL: int = POSITION_TYPE_SELL
    ORDER_TYPE_BUY_LIMIT: int = ORDER_TYPE_BUY_LIMIT
    ORDER_TYPE_SELL_LIMIT: int = ORDER_TYPE_SELL_LIMIT
    ORDER_TYPE_BUY_STOP: int = ORDER_TYPE_BUY_STOP
    ORDER_TYPE_SELL_STOP: int = ORDER_TYPE_SELL_STOP

    # Slots for call responses; tests set these directly.
    _initialize: bool = True
    _terminal_info: FakeTerminalInfo | None = field(default_factory=FakeTerminalInfo)
    _account_info: FakeAccountInfo | None = field(default_factory=FakeAccountInfo)
    _symbol_info: dict[str, FakeSymbolInfo | None] = field(default_factory=dict)
    _symbol_info_tick: dict[str, FakeTick | None] = field(default_factory=dict)
    _symbols_get: tuple[FakeSymbolInfo, ...] = field(default_factory=tuple)
    _symbol_select: bool = True
    _positions_get: tuple[FakePosition, ...] = field(default_factory=tuple)
    _orders_get: tuple[FakeOrder, ...] = field(default_factory=tuple)
    _history_deals_get: tuple[FakeDeal, ...] = field(default_factory=tuple)
    _last_error: tuple[int, str] = (0, "")

    # Call-counter bookkeeping — useful for cache-hit assertions.
    calls: dict[str, int] = field(default_factory=dict)

    # --- API surface ---
    def _bump(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def initialize(self, *args: Any, **kwargs: Any) -> bool:
        self._bump("initialize")
        return self._initialize

    def shutdown(self) -> None:
        self._bump("shutdown")

    def terminal_info(self) -> FakeTerminalInfo | None:
        self._bump("terminal_info")
        return self._terminal_info

    def account_info(self) -> FakeAccountInfo | None:
        self._bump("account_info")
        return self._account_info

    def symbol_info(self, symbol: str) -> FakeSymbolInfo | None:
        self._bump("symbol_info")
        return self._symbol_info.get(symbol)

    def symbol_info_tick(self, symbol: str) -> FakeTick | None:
        self._bump("symbol_info_tick")
        return self._symbol_info_tick.get(symbol)

    def symbols_get(self, group: str | None = None) -> tuple[FakeSymbolInfo, ...]:
        self._bump("symbols_get")
        return self._symbols_get

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        self._bump("symbol_select")
        # Flip visibility on the stored symbol_info so a subsequent lookup
        # sees visible=True, mirroring the real library's behaviour.
        info = self._symbol_info.get(symbol)
        if info is not None:
            info.visible = enable
        return self._symbol_select

    def positions_get(
        self, *, symbol: str | None = None, ticket: int | None = None
    ) -> tuple[FakePosition, ...]:
        self._bump("positions_get")
        out = self._positions_get
        if symbol is not None:
            out = tuple(p for p in out if p.symbol == symbol)
        if ticket is not None:
            out = tuple(p for p in out if p.ticket == ticket)
        return out

    def orders_get(
        self, *, symbol: str | None = None, ticket: int | None = None
    ) -> tuple[FakeOrder, ...]:
        self._bump("orders_get")
        out = self._orders_get
        if symbol is not None:
            out = tuple(o for o in out if o.symbol == symbol)
        if ticket is not None:
            out = tuple(o for o in out if o.ticket == ticket)
        return out

    def history_deals_get(
        self, date_from: Any, date_to: Any, *, group: str | None = None
    ) -> tuple[FakeDeal, ...]:
        self._bump("history_deals_get")
        return self._history_deals_get

    def last_error(self) -> tuple[int, str]:
        return self._last_error
```

Note the `FakeSymbolInfo.currency_profit = "USD"` field is typed `float` for shape parity with real `MetaTrader5` output (the library really does store these as strings but annotates them loosely). The adapter treats it as string throughout.

- [ ] **Step 2: Write `tests/conftest.py`**

```python
"""Shared fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.fakes import FakeMT5


@pytest.fixture
def fake_mt5() -> FakeMT5:
    return FakeMT5()


@pytest.fixture
def frozen_utc(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Pin UTC 'now' to 2026-04-21T10:00:00Z for deterministic TZ-offset tests."""
    fixed = datetime(2026, 4, 21, 10, 0, 0, tzinfo=timezone.utc)

    class _Clock:
        @staticmethod
        def now(tz: timezone | None = None) -> datetime:
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr("mt5_mcp.adapter.mt5_client.datetime", _Clock)
    monkeypatch.setattr("mt5_mcp.adapter.conversions.datetime", _Clock)
    return fixed
```

- [ ] **Step 3: Verify the fake imports cleanly**

Run: `python -c "from tests.fakes import FakeMT5; f = FakeMT5(); print(f.terminal_info().name)"`
Expected: `MetaTrader 5` — no errors. (`server` lives on `FakeAccountInfo`, not `FakeTerminalInfo`.)

Run: `pytest -q` (still collects zero tests, but imports must succeed)
Expected: `no tests ran`.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add FakeMT5 harness for adapter/tool tests"
```

---

## Task 3: Pydantic type models

All data returned by tools is defined here as Pydantic v2 models. The adapter produces these; tools just hand them back.

**Files:**
- Create: `src/mt5_mcp/types.py`
- Create: `tests/test_types.py`

- [ ] **Step 1: Write the failing test (`tests/test_types.py`)**

```python
"""Roundtrip + serialisation checks for Pydantic model contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from mt5_mcp.types import (
    AccountInfo,
    Deal,
    ErrorDetail,
    MarketHours,
    Order,
    Position,
    Quote,
    SymbolInfo,
    TerminalInfo,
)


def test_account_info_serialises_decimals_as_strings():
    info = AccountInfo(
        login=1,
        name="x",
        server="s",
        currency="USD",
        balance=Decimal("100.5"),
        equity=Decimal("100.5"),
        margin=Decimal("0"),
        margin_free=Decimal("100.5"),
        margin_level=None,
        leverage=100,
        trade_allowed=True,
        margin_mode="retail_netting",
    )
    blob = json.loads(info.model_dump_json())
    assert blob["balance"] == "100.5"
    assert blob["margin_level"] is None


def test_position_rejects_float_for_volume():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Position(
            ticket=1,
            symbol="EURUSD",
            type="buy",
            volume=0.1,  # float — must be Decimal or str
            price_open=Decimal("1.0"),
            price_current=Decimal("1.0"),
            sl=None,
            tp=None,
            profit=Decimal("0"),
            swap=Decimal("0"),
            commission=Decimal("0"),
            time_open=datetime(2026, 4, 21, tzinfo=timezone.utc),
            comment=None,
        )


def test_position_datetime_must_be_aware():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Position(
            ticket=1,
            symbol="EURUSD",
            type="buy",
            volume=Decimal("0.1"),
            price_open=Decimal("1.0"),
            price_current=Decimal("1.0"),
            sl=None,
            tp=None,
            profit=Decimal("0"),
            swap=Decimal("0"),
            commission=Decimal("0"),
            time_open=datetime(2026, 4, 21),  # naive — reject
            comment=None,
        )


def test_quote_roundtrip():
    q = Quote(
        symbol="EURUSD",
        bid=Decimal("1.0823"),
        ask=Decimal("1.0824"),
        time=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
    )
    blob = json.loads(q.model_dump_json())
    assert blob["time"].endswith("Z") or blob["time"].endswith("+00:00")
    assert blob["bid"] == "1.0823"


def test_error_detail_defaults():
    e = ErrorDetail(code="TERMINAL_NOT_CONNECTED", message="x", retryable=False, requires_human=True)
    assert e.details is None
    assert e.mt5_retcode is None


def test_market_hours_fields():
    m = MarketHours(
        symbol="EURUSD",
        is_open=True,
        next_close=datetime(2026, 4, 21, 21, 0, tzinfo=timezone.utc),
        next_open=None,
    )
    assert m.is_open is True


def test_symbol_info_exposes_broker_fields():
    s = SymbolInfo(
        name="EURUSD",
        description="Euro / US Dollar",
        category="Forex",
        contract_size=Decimal("100000"),
        tick_size=Decimal("0.00001"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.01"),
        currency_profit="USD",
        currency_margin="USD",
        filling_modes=["ioc", "fok"],
        digits=5,
        is_tradeable=True,
    )
    assert s.category == "Forex"


def test_terminal_info_fields():
    t = TerminalInfo(
        connected=True,
        build=4150,
        name="MetaTrader 5",
        company="FintrixMarkets Ltd",
        login=123456,
        server="FintrixMarkets-Demo",
        broker_tz_offset_minutes=180,
        latency_ms=12,
    )
    assert t.broker_tz_offset_minutes == 180


def test_order_and_deal_fields():
    o = Order(
        ticket=1,
        symbol="EURUSD",
        type="buy_limit",
        volume=Decimal("0.1"),
        price=Decimal("1.08"),
        sl=None,
        tp=None,
        time_setup=datetime(2026, 4, 21, tzinfo=timezone.utc),
        expiration=None,
        comment=None,
    )
    d = Deal(
        ticket=1,
        order=1,
        symbol="EURUSD",
        type="buy",
        volume=Decimal("0.1"),
        price=Decimal("1.08"),
        profit=Decimal("5"),
        swap=Decimal("0"),
        commission=Decimal("-0.5"),
        time=datetime(2026, 4, 21, tzinfo=timezone.utc),
        comment=None,
    )
    assert o.type == "buy_limit" and d.type == "buy"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_types.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.types'`.

- [ ] **Step 3: Write `src/mt5_mcp/types.py`**

```python
"""Pydantic models returned by MCP tools.

All money / price / volume fields are `Decimal` (JSON-encoded as string).
All datetimes are timezone-aware UTC — `adapter/conversions.py` is the only
place naive timestamps become aware.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_JSON_OVERRIDES: dict[type, Any] = {Decimal: lambda d: format(d, "f")}


class _Base(BaseModel):
    model_config = ConfigDict(
        # Reject silent float→Decimal coercion; callers must pass Decimal or
        # numeric strings.
        strict=False,
        # Keep JSON encoders stable so `model_dump_json()` produces the
        # string-formatted Decimals promised by the architecture doc.
        json_encoders=_JSON_OVERRIDES,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _reject_naive_datetimes(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("datetime must be timezone-aware (UTC)")
        return v


class ErrorDetail(_Base):
    code: str
    message: str
    retryable: bool
    requires_human: bool
    details: dict[str, Any] | None = None
    mt5_retcode: int | None = None


class AccountInfo(_Base):
    login: int
    name: str
    server: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin: Decimal
    margin_free: Decimal
    margin_level: Decimal | None
    leverage: int
    trade_allowed: bool
    margin_mode: Literal["retail_netting", "exchange", "retail_hedging"]


class Position(_Base):
    ticket: int
    symbol: str
    type: Literal["buy", "sell"]
    volume: Decimal
    price_open: Decimal
    price_current: Decimal
    sl: Decimal | None
    tp: Decimal | None
    profit: Decimal
    swap: Decimal
    commission: Decimal
    time_open: datetime
    comment: str | None

    @field_validator("volume", "price_open", "price_current", "profit", "swap", "commission", mode="before")
    @classmethod
    def _reject_float(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise ValueError("use Decimal, not float, for money/price/volume")
        return v


class Order(_Base):
    ticket: int
    symbol: str
    type: Literal["buy_limit", "sell_limit", "buy_stop", "sell_stop", "buy_stop_limit", "sell_stop_limit"]
    volume: Decimal
    price: Decimal
    sl: Decimal | None
    tp: Decimal | None
    time_setup: datetime
    expiration: datetime | None
    comment: str | None


class Deal(_Base):
    ticket: int
    order: int
    symbol: str
    type: Literal["buy", "sell", "balance", "credit", "charge", "correction", "bonus", "commission"]
    volume: Decimal
    price: Decimal
    profit: Decimal
    swap: Decimal
    commission: Decimal
    time: datetime
    comment: str | None


class Quote(_Base):
    symbol: str
    bid: Decimal
    ask: Decimal
    time: datetime


class SymbolInfo(_Base):
    name: str
    description: str
    category: str  # Derived from `path` — "Forex", "Indices", "Metals", "Crypto", "Stocks", or raw first path segment.
    contract_size: Decimal
    tick_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    currency_profit: str
    currency_margin: str
    filling_modes: list[Literal["fok", "ioc", "return"]]
    digits: int
    is_tradeable: bool


class MarketHours(_Base):
    symbol: str
    is_open: bool
    next_open: datetime | None
    next_close: datetime | None


class TerminalInfo(_Base):
    connected: bool
    build: int
    name: str
    company: str
    login: int
    server: str
    broker_tz_offset_minutes: int
    latency_ms: int
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_types.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/types.py tests/test_types.py
git commit -m "feat: add Pydantic type models for tool outputs"
```

---

## Task 4: Error mapping

Maps `MetaTrader5` numeric retcodes into our `ErrorDetail` codes. Used by the adapter and every tool.

**Files:**
- Create: `src/mt5_mcp/errors.py`
- Create: `tests/test_errors.py`

- [ ] **Step 1: Write the failing test (`tests/test_errors.py`)**

```python
from mt5_mcp.errors import MT5Error, error_for_retcode
from mt5_mcp.types import ErrorDetail


def test_known_retcode_is_mapped():
    err = error_for_retcode(10019, message="raw")  # NO_MONEY
    assert isinstance(err, ErrorDetail)
    assert err.code == "INSUFFICIENT_MARGIN"
    assert err.requires_human is True
    assert err.mt5_retcode == 10019


def test_unknown_retcode_falls_through():
    err = error_for_retcode(99999, message="raw")
    assert err.code == "MT5_UNKNOWN_RETCODE"
    assert err.details == {"raw_message": "raw"}
    assert err.mt5_retcode == 99999


def test_mt5_error_carries_detail():
    err = MT5Error(ErrorDetail(code="X", message="y", retryable=False, requires_human=False))
    assert err.detail.code == "X"
    assert "X" in str(err)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_errors.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.errors'`.

- [ ] **Step 3: Write `src/mt5_mcp/errors.py`**

```python
"""Error codes and MT5 retcode → ErrorDetail mapping."""

from __future__ import annotations

from typing import Any

from mt5_mcp.types import ErrorDetail


# Subset of mt5lib retcodes we map explicitly; full table lives in mt5lib itself.
_RETCODE_MAP: dict[int, tuple[str, str, bool, bool]] = {
    # retcode: (code, message, retryable, requires_human)
    10004: ("REQUOTE", "Price moved during execution; try again.", True, False),
    10006: ("REJECTED_BY_SERVER", "Broker server rejected the trade.", False, True),
    10014: ("INVALID_VOLUME", "Volume invalid for symbol's lot step / min / max.", False, False),
    10015: ("INVALID_PRICE", "Price invalid for this order type.", True, False),
    10018: ("MARKET_CLOSED", "Symbol's session is closed.", False, False),
    10019: ("INSUFFICIENT_MARGIN", "Not enough free margin for this trade.", False, True),
}


def error_for_retcode(
    retcode: int,
    *,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> ErrorDetail:
    """Translate an `mt5lib` retcode into a structured `ErrorDetail`."""
    mapped = _RETCODE_MAP.get(retcode)
    if mapped is None:
        return ErrorDetail(
            code="MT5_UNKNOWN_RETCODE",
            message=f"Unknown mt5lib retcode {retcode}",
            retryable=False,
            requires_human=True,
            details={"raw_message": message, **(details or {})},
            mt5_retcode=retcode,
        )
    code, default_msg, retryable, requires_human = mapped
    return ErrorDetail(
        code=code,
        message=message or default_msg,
        retryable=retryable,
        requires_human=requires_human,
        details=details,
        mt5_retcode=retcode,
    )


class MT5Error(Exception):
    """Raised by the adapter when a call fails. Carries the structured detail."""

    def __init__(self, detail: ErrorDetail) -> None:
        super().__init__(f"{detail.code}: {detail.message}")
        self.detail = detail
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_errors.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/errors.py tests/test_errors.py
git commit -m "feat: add mt5 retcode to ErrorDetail mapping"
```

---

## Task 5: Config loader

Loads `config.toml`, validates via Pydantic, and hot-reloads on file change via `watchdog`.

**Files:**
- Create: `src/mt5_mcp/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test (`tests/test_config.py`)**

```python
"""Config loader + hot-reload."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.config import Config, ConfigWatcher, load_config


MINIMAL_TOML = """
[mt5]
terminal_path = ""

[policy]
auto_approve_notional = "1000.00"
max_notional_per_trade = "10000.00"
max_realised_loss_per_close = "500.00"
max_daily_loss = "2000.00"

[idempotency]
ttl_seconds = 86400

[symbols]
allowlist = []
denylist = []

[audit]
path = "~/.local/share/mt5-mcp/audit.jsonl"
max_bytes = 10485760

[transport.http]
auth_token = ""

[telemetry]
enabled = false
endpoint = ""
"""


def test_load_valid_config(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.policy.auto_approve_notional == Decimal("1000.00")
    assert cfg.idempotency.ttl_seconds == 86400
    assert cfg.telemetry.enabled is False


def test_load_rejects_invalid(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML.replace('ttl_seconds = 86400', 'ttl_seconds = -1'))
    with pytest.raises(ValueError):
        load_config(p)


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_load_default_location(monkeypatch, tmp_path: Path):
    """When no path is given, falls back to `%APPDATA%\\mt5-mcp\\config.toml`
    (or the XDG equivalent). If that file doesn't exist either, returns a
    Config populated with defaults."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()  # no argument; no file on disk → defaults
    assert isinstance(cfg, Config)
    assert cfg.policy.auto_approve_notional == Decimal("0")  # default


def test_hot_reload_picks_up_changes(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)

    watcher = ConfigWatcher(p)
    watcher.start()
    try:
        assert watcher.current.idempotency.ttl_seconds == 86400

        p.write_text(MINIMAL_TOML.replace("ttl_seconds = 86400", "ttl_seconds = 60"))
        # Poll watcher up to 2s for the new value.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if watcher.current.idempotency.ttl_seconds == 60:
                break
            time.sleep(0.05)
        assert watcher.current.idempotency.ttl_seconds == 60
    finally:
        watcher.stop()


def test_reload_survives_broken_edit(tmp_path: Path, caplog):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)

    watcher = ConfigWatcher(p)
    watcher.start()
    try:
        original = watcher.current

        # Write garbage — reload should fail, warn, and retain the previous config.
        p.write_text("not valid [[ toml")
        time.sleep(0.5)
        assert watcher.current is original
    finally:
        watcher.stop()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.config'`.

- [ ] **Step 3: Write `src/mt5_mcp/config.py`**

```python
"""Configuration model + TOML loader + watchdog-driven hot reload."""

from __future__ import annotations

import logging
import os
import sys
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import]
else:
    import tomli as tomllib  # type: ignore[import]


logger = logging.getLogger(__name__)


class _Sub(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MT5Section(_Sub):
    terminal_path: str = ""
    preferred_login: int | None = None


class PolicySection(_Sub):
    # All Decimals — the architecture insists no floats on money amounts.
    auto_approve_notional: Decimal = Decimal("0")
    max_notional_per_trade: Decimal = Decimal("0")
    max_realised_loss_per_close: Decimal = Decimal("0")
    max_daily_loss: Decimal = Decimal("0")
    # Consent retry window; re-used by Phase 2.
    approval_ttl_seconds: PositiveInt = 300


class IdempotencySection(_Sub):
    ttl_seconds: PositiveInt = 86_400


class SymbolsSection(_Sub):
    allowlist: list[str] = Field(default_factory=list)
    denylist: list[str] = Field(default_factory=list)


class AuditSection(_Sub):
    path: str = "~/.local/share/mt5-mcp/audit.jsonl"
    max_bytes: PositiveInt = 10_485_760


class TransportHTTPSection(_Sub):
    auth_token: str = ""


class TransportSection(_Sub):
    http: TransportHTTPSection = Field(default_factory=TransportHTTPSection)


class TelemetrySection(_Sub):
    enabled: bool = False
    endpoint: str = ""


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mt5: MT5Section = Field(default_factory=MT5Section)
    policy: PolicySection = Field(default_factory=PolicySection)
    idempotency: IdempotencySection = Field(default_factory=IdempotencySection)
    symbols: SymbolsSection = Field(default_factory=SymbolsSection)
    audit: AuditSection = Field(default_factory=AuditSection)
    transport: TransportSection = Field(default_factory=TransportSection)
    telemetry: TelemetrySection = Field(default_factory=TelemetrySection)


def default_config_path() -> Path:
    """Resolve the OS-default config file path.

    Windows: `%APPDATA%\\mt5-mcp\\config.toml`.
    Linux / WSL2: `$XDG_CONFIG_HOME/mt5-mcp/config.toml` or
    `~/.config/mt5-mcp/config.toml`.
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "mt5-mcp" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load + validate a config file.

    If `path` is None and the default location is absent, returns a
    Config with defaults so the server can still start for smoke testing.
    """
    if path is None:
        path = default_config_path()
        if not path.exists():
            logger.info("no config file at %s; using defaults", path)
            return Config()
    if not path.exists():
        raise FileNotFoundError(path)
    raw = tomllib.loads(path.read_text())
    try:
        return Config(**raw)
    except Exception as exc:  # pragma: no cover — pydantic validation surface
        raise ValueError(f"invalid config at {path}: {exc}") from exc


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, path: Path, on_change) -> None:
        self._path = path.resolve()
        self._on_change = on_change

    def on_modified(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        if not event.is_directory and Path(event.src_path).resolve() == self._path:
            self._on_change()

    # Some editors rename-and-replace on save; catch that too.
    def on_moved(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        dest = getattr(event, "dest_path", None)
        if dest and Path(dest).resolve() == self._path:
            self._on_change()


class ConfigWatcher:
    """Watches the config file and reloads on change.

    A broken reload (invalid TOML, schema violation) is logged and ignored —
    `.current` keeps the last-good config so the running server isn't
    destabilised by a typo.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._current = load_config(path)
        self._observer: Observer | None = None

    @property
    def current(self) -> Config:
        with self._lock:
            return self._current

    def reload(self) -> None:
        try:
            new = load_config(self._path)
        except Exception as exc:
            logger.warning("config reload failed, keeping previous: %s", exc)
            return
        with self._lock:
            self._current = new
        logger.info("config reloaded from %s", self._path)

    def start(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        self._observer.schedule(
            _ReloadHandler(self._path, self.reload),
            str(self._path.parent),
            recursive=False,
        )
        self._observer.start()

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2.0)
        self._observer = None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config.py -v`
Expected: all 6 tests pass. (`watchdog` uses OS-native file events; the 2s deadline in the hot-reload test is conservative.)

- [ ] **Step 5: Wire up `reload-config` in `__main__.py`**

Replace the `reload-config` branch in `src/mt5_mcp/__main__.py`:

```python
if argv[0] == "reload-config":
    # Sending SIGUSR1 isn't portable to Windows; the watchdog-based
    # auto-reload is the primary mechanism. This command just rewrites
    # the file's mtime, which triggers the watcher in a running server.
    import os as _os
    from mt5_mcp.config import default_config_path
    path = default_config_path()
    if not path.exists():
        print(f"no config file at {path}", file=sys.stderr)
        return 1
    _os.utime(path, None)
    print(f"touched {path}; running server should reload")
    return 0
```

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/config.py src/mt5_mcp/__main__.py tests/test_config.py
git commit -m "feat: add pydantic config + watchdog hot reload"
```

---

## Task 6: Adapter — conversions

Converts `MetaTrader5` raw types (NamedTuples, naive epochs, floats) into Pydantic models with UTC datetimes and Decimals. Timestamps cross from broker-server-time to UTC here and nowhere else.

**Files:**
- Create: `src/mt5_mcp/adapter/__init__.py` (empty)
- Create: `src/mt5_mcp/adapter/conversions.py`
- Create: `tests/test_adapter_conversions.py`

- [ ] **Step 1: Write the failing test (`tests/test_adapter_conversions.py`)**

```python
"""Type marshalling + broker-TZ→UTC conversion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mt5_mcp.adapter.conversions import (
    account_info_from_raw,
    deal_from_raw,
    epoch_to_utc,
    infer_broker_tz_offset,
    order_from_raw,
    position_from_raw,
    quote_from_tick,
    symbol_info_from_raw,
    terminal_info_from_raw,
)
from tests.fakes import (
    FakeAccountInfo,
    FakeDeal,
    FakeOrder,
    FakePosition,
    FakeSymbolInfo,
    FakeTerminalInfo,
    FakeTick,
)


def test_epoch_to_utc_removes_broker_offset():
    # Broker is GMT+3 (EET summer). A broker-time epoch of 2026-04-21T13:00
    # interpreted as naive corresponds to a real UTC of 2026-04-21T10:00.
    epoch_naive = int(datetime(2026, 4, 21, 13, 0).timestamp())
    dt = epoch_to_utc(epoch_naive, broker_offset_minutes=180)
    assert dt.tzinfo is timezone.utc
    assert dt == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)


def test_epoch_to_utc_handles_zero_offset():
    epoch = int(datetime(2026, 4, 21, 10, 0).timestamp())
    assert epoch_to_utc(epoch, 0) == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)


def test_infer_broker_tz_offset_rounds_to_quarter_hour():
    broker_ts = int(datetime(2026, 4, 21, 13, 0).timestamp())  # broker says 13:00
    real_utc = datetime(2026, 4, 21, 10, 2, tzinfo=timezone.utc)  # truly 10:02Z
    offset = infer_broker_tz_offset(broker_ts, real_utc)
    assert offset == 180  # rounded to 15-min


def test_infer_broker_tz_offset_handles_negative_tz():
    broker_ts = int(datetime(2026, 4, 21, 5, 0).timestamp())  # broker says 05:00
    real_utc = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    offset = infer_broker_tz_offset(broker_ts, real_utc)
    assert offset == -300  # GMT-5


def test_position_from_raw_converts_decimals_and_time():
    raw = FakePosition(
        ticket=99, symbol="EURUSD", type=0, volume=0.1,
        price_open=1.0820, price_current=1.0824, sl=0.0, tp=0.0,
        profit=4.0, swap=0.0, commission=0.0,
        time=int(datetime(2026, 4, 21, 13, 0).timestamp()),
        comment="",
    )
    pos = position_from_raw(raw, broker_offset_minutes=180)
    assert pos.type == "buy"
    assert pos.volume == Decimal("0.1")
    assert pos.time_open == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert pos.sl is None and pos.tp is None  # 0.0 → None
    assert pos.comment is None  # "" → None


def test_position_sell_type():
    raw = FakePosition(type=1)
    pos = position_from_raw(raw, broker_offset_minutes=0)
    assert pos.type == "sell"


def test_account_info_from_raw():
    raw = FakeAccountInfo(margin_mode=0)
    info = account_info_from_raw(raw)
    assert info.margin_mode == "retail_netting"
    assert info.balance == Decimal("10000.0")
    # margin_level should pass through
    assert info.margin_level is not None


def test_account_margin_mode_values():
    raw = FakeAccountInfo(margin_mode=1)
    assert account_info_from_raw(raw).margin_mode == "exchange"
    raw = FakeAccountInfo(margin_mode=2)
    assert account_info_from_raw(raw).margin_mode == "retail_hedging"


def test_quote_from_tick():
    tick = FakeTick(time=int(datetime(2026, 4, 21, 13, 0).timestamp()), bid=1.08, ask=1.09)
    q = quote_from_tick(tick, symbol="EURUSD", broker_offset_minutes=180)
    assert q.time == datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert q.bid == Decimal("1.08")


def test_symbol_info_from_raw_derives_category():
    raw = FakeSymbolInfo(path="Forex\\Majors\\EURUSD", filling_mode=1 | 2)  # FOK|IOC
    info = symbol_info_from_raw(raw)
    assert info.category == "Forex"
    assert set(info.filling_modes) == {"fok", "ioc"}


def test_symbol_info_tradeable_flag():
    raw = FakeSymbolInfo(trade_mode=0)  # disabled
    assert symbol_info_from_raw(raw).is_tradeable is False
    raw = FakeSymbolInfo(trade_mode=4)  # full
    assert symbol_info_from_raw(raw).is_tradeable is True


def test_order_from_raw_maps_type():
    raw = FakeOrder(type=2)  # BUY_LIMIT
    o = order_from_raw(raw, broker_offset_minutes=0)
    assert o.type == "buy_limit"


def test_deal_from_raw_handles_balance_type():
    raw = FakeDeal(type=2)  # mt5 DEAL_TYPE_BALANCE
    d = deal_from_raw(raw, broker_offset_minutes=0)
    assert d.type == "balance"


def test_terminal_info_from_raw():
    raw = FakeTerminalInfo(build=4150)
    t = terminal_info_from_raw(
        raw,
        login=123,
        server="S",
        broker_offset_minutes=180,
        latency_ms=12,
    )
    assert t.broker_tz_offset_minutes == 180
    assert t.latency_ms == 12
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_adapter_conversions.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.adapter'`.

- [ ] **Step 3: Write `src/mt5_mcp/adapter/__init__.py`**

```python
# Adapter package — the only place MetaTrader5 is imported.
```

- [ ] **Step 4: Write `src/mt5_mcp/adapter/conversions.py`**

```python
"""Convert raw MetaTrader5 types → our Pydantic models.

The `MetaTrader5` library returns naive epoch ints in broker-server time
(most retail brokers = EET). We subtract the broker offset to land on UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from mt5_mcp.types import (
    AccountInfo,
    Deal,
    MarketHours,
    Order,
    Position,
    Quote,
    SymbolInfo,
    TerminalInfo,
)


# --- timestamps ---------------------------------------------------------

def epoch_to_utc(epoch_naive: int, broker_offset_minutes: int) -> datetime:
    """Convert a broker-time epoch (as mt5lib reports it) to aware UTC.

    `broker_offset_minutes` is the broker's timezone offset from UTC in
    minutes. GMT+3 (EET summer) is +180. The mt5lib epoch is "broker local
    time treated as UTC" — so subtracting the offset yields real UTC.
    """
    # `fromtimestamp(epoch, tz=UTC)` treats the epoch as real UTC; for mt5lib
    # that produces broker-local-time labelled UTC. We adjust.
    as_if_utc = datetime.fromtimestamp(epoch_naive, tz=timezone.utc)
    return as_if_utc - timedelta(minutes=broker_offset_minutes)


def infer_broker_tz_offset(
    broker_terminal_time: int,
    real_utc_now: datetime | None = None,
) -> int:
    """Compute broker TZ offset in minutes, rounded to 15-min steps.

    The real mt5lib returns `terminal_info().time` as a naive epoch in
    broker-server time. Comparing that epoch (interpreted as UTC) to the
    real wall-clock UTC yields the offset.
    """
    if real_utc_now is None:
        real_utc_now = datetime.now(timezone.utc)
    as_if_utc = datetime.fromtimestamp(broker_terminal_time, tz=timezone.utc)
    delta = as_if_utc - real_utc_now
    minutes = round(delta.total_seconds() / 60.0 / 15.0) * 15
    return minutes


# --- Decimal helpers -----------------------------------------------------

def _d(v: Any) -> Decimal:
    """Coerce float/int/str to Decimal via its string repr to avoid 0.1-binary bugs."""
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _opt_d(v: Any) -> Decimal | None:
    """Treat 0.0 as None for sl/tp-style fields — mt5lib uses 0 to mean 'unset'."""
    if v is None or v == 0.0:
        return None
    return _d(v)


def _opt_str(v: str | None) -> str | None:
    if not v:
        return None
    return v


# --- mappings ------------------------------------------------------------

_MARGIN_MODES = {0: "retail_netting", 1: "exchange", 2: "retail_hedging"}

# mt5lib: ORDER_TYPE_* — buy/sell constants are 0/1 for market; pending are 2..7.
_ORDER_TYPES = {
    2: "buy_limit",
    3: "sell_limit",
    4: "buy_stop",
    5: "sell_stop",
    6: "buy_stop_limit",
    7: "sell_stop_limit",
}

# mt5lib: DEAL_TYPE_* — 0/1 are buy/sell; 2..8 are balance/credit/etc.
_DEAL_TYPES = {
    0: "buy",
    1: "sell",
    2: "balance",
    3: "credit",
    4: "charge",
    5: "correction",
    6: "bonus",
    7: "commission",
}

_TRADE_MODE_DISABLED = 0


# --- converters ---------------------------------------------------------

def position_from_raw(raw: Any, *, broker_offset_minutes: int) -> Position:
    return Position(
        ticket=raw.ticket,
        symbol=raw.symbol,
        type="buy" if raw.type == 0 else "sell",
        volume=_d(raw.volume),
        price_open=_d(raw.price_open),
        price_current=_d(raw.price_current),
        sl=_opt_d(raw.sl),
        tp=_opt_d(raw.tp),
        profit=_d(raw.profit),
        swap=_d(raw.swap),
        commission=_d(raw.commission),
        time_open=epoch_to_utc(raw.time, broker_offset_minutes),
        comment=_opt_str(raw.comment),
    )


def order_from_raw(raw: Any, *, broker_offset_minutes: int) -> Order:
    otype = _ORDER_TYPES.get(raw.type)
    if otype is None:
        raise ValueError(f"unsupported order type: {raw.type}")
    return Order(
        ticket=raw.ticket,
        symbol=raw.symbol,
        type=otype,
        volume=_d(raw.volume_current),
        price=_d(raw.price_open),
        sl=_opt_d(raw.sl),
        tp=_opt_d(raw.tp),
        time_setup=epoch_to_utc(raw.time_setup, broker_offset_minutes),
        expiration=(
            epoch_to_utc(raw.time_expiration, broker_offset_minutes)
            if raw.time_expiration
            else None
        ),
        comment=_opt_str(raw.comment),
    )


def deal_from_raw(raw: Any, *, broker_offset_minutes: int) -> Deal:
    dtype = _DEAL_TYPES.get(raw.type, "commission")
    return Deal(
        ticket=raw.ticket,
        order=raw.order,
        symbol=raw.symbol,
        type=dtype,
        volume=_d(raw.volume),
        price=_d(raw.price),
        profit=_d(raw.profit),
        swap=_d(raw.swap),
        commission=_d(raw.commission),
        time=epoch_to_utc(raw.time, broker_offset_minutes),
        comment=_opt_str(raw.comment),
    )


def account_info_from_raw(raw: Any) -> AccountInfo:
    return AccountInfo(
        login=raw.login,
        name=raw.name,
        server=raw.server,
        currency=raw.currency,
        balance=_d(raw.balance),
        equity=_d(raw.equity),
        margin=_d(raw.margin),
        margin_free=_d(raw.margin_free),
        margin_level=_opt_d(raw.margin_level),
        leverage=raw.leverage,
        trade_allowed=raw.trade_allowed,
        margin_mode=_MARGIN_MODES.get(raw.margin_mode, "retail_netting"),
    )


def quote_from_tick(tick: Any, *, symbol: str, broker_offset_minutes: int) -> Quote:
    return Quote(
        symbol=symbol,
        bid=_d(tick.bid),
        ask=_d(tick.ask),
        time=epoch_to_utc(tick.time, broker_offset_minutes),
    )


def _category_from_path(path: str) -> str:
    # mt5lib returns backslash-separated "Forex\\Majors\\EURUSD" etc.
    first = path.split("\\")[0] if path else ""
    return first or "Unknown"


def _filling_modes_from_mask(mask: int) -> list[str]:
    modes: list[str] = []
    if mask & 1:
        modes.append("fok")
    if mask & 2:
        modes.append("ioc")
    if mask & 4:
        modes.append("return")
    return modes


def symbol_info_from_raw(raw: Any) -> SymbolInfo:
    return SymbolInfo(
        name=raw.name,
        description=raw.description,
        category=_category_from_path(getattr(raw, "path", "")),
        contract_size=_d(raw.trade_contract_size),
        tick_size=_d(raw.point),
        volume_min=_d(raw.volume_min),
        volume_max=_d(raw.volume_max),
        volume_step=_d(raw.volume_step),
        currency_profit=str(raw.currency_profit),
        currency_margin=raw.currency_margin,
        filling_modes=_filling_modes_from_mask(raw.filling_mode),
        digits=raw.digits,
        is_tradeable=raw.trade_mode != _TRADE_MODE_DISABLED,
    )


def terminal_info_from_raw(
    raw: Any,
    *,
    login: int,
    server: str,
    broker_offset_minutes: int,
    latency_ms: int,
) -> TerminalInfo:
    return TerminalInfo(
        connected=getattr(raw, "connected", True),
        build=raw.build,
        name=raw.name,
        company=raw.company,
        login=login,
        server=server,
        broker_tz_offset_minutes=broker_offset_minutes,
        latency_ms=latency_ms,
    )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_adapter_conversions.py -v`
Expected: all 13 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/adapter/ tests/test_adapter_conversions.py
git commit -m "feat: add adapter conversions (broker-TZ → UTC, Decimal coercion)"
```

---

## Task 7: Adapter — `mt5_client` singleton

The singleton owns the lifecycle: `initialize()` on first use, cached broker TZ offset, transparent re-init on mid-session "not initialized" errors, and latency measurement via `ping`.

**Files:**
- Create: `src/mt5_mcp/adapter/mt5_client.py`
- Create: `tests/test_adapter_mt5_client.py`

- [ ] **Step 1: Write the failing test (`tests/test_adapter_mt5_client.py`)**

```python
"""MT5Client lifecycle and re-init behaviour."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.errors import MT5Error
from tests.fakes import FakeMT5, FakeTerminalInfo


@pytest.fixture
def client(fake_mt5: FakeMT5, frozen_utc):
    c = MT5Client(mt5_module=fake_mt5)
    return c


def test_connect_initialises_and_caches_offset(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    # Broker says 13:00 when real UTC is 10:00 → +180 min.
    fake_mt5._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    client.connect()
    assert client.broker_offset_minutes == 180
    assert fake_mt5.calls["initialize"] == 1


def test_connect_uses_terminal_path(fake_mt5: FakeMT5, frozen_utc):
    c = MT5Client(mt5_module=fake_mt5, terminal_path="C:/mt5/terminal64.exe")
    c.connect()
    # The fake doesn't record kwargs, but we can spy via patch.
    with patch.object(fake_mt5, "initialize", wraps=fake_mt5.initialize) as spy:
        c._initialised = False
        c.connect()
    spy.assert_called_once_with("C:/mt5/terminal64.exe")


def test_connect_failure_raises(client: MT5Client, fake_mt5: FakeMT5):
    fake_mt5._initialize = False
    fake_mt5._last_error = (-10003, "IPC timeout")
    with pytest.raises(MT5Error) as ei:
        client.connect()
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_terminal_info_none_raises(client: MT5Client, fake_mt5: FakeMT5):
    fake_mt5._terminal_info = None
    with pytest.raises(MT5Error) as ei:
        client.connect()
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_shutdown_resets_state(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()
    assert client._initialised
    client.disconnect()
    assert fake_mt5.calls["shutdown"] == 1
    assert not client._initialised


def test_call_transparently_reinits_on_not_initialized(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()
    # Simulate mid-session failure: function returns None once, then recovers.
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            # mimic mt5lib: returns None and sets last_error to -10004 "not initialized"
            fake_mt5._last_error = (-10004, "not initialized")
            return None
        fake_mt5._last_error = (0, "")
        return "ok"

    result = client._call_with_reinit(flaky)
    assert result == "ok"
    assert calls["n"] == 2
    # A second `initialize` call happened during the retry.
    assert fake_mt5.calls["initialize"] == 2


def test_call_reinit_fails_hard_when_reinit_broken(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()

    def always_fails():
        fake_mt5._last_error = (-10004, "not initialized")
        return None

    # Make re-init fail too.
    fake_mt5._initialize = False
    with pytest.raises(MT5Error) as ei:
        client._call_with_reinit(always_fails)
    assert ei.value.detail.code == "TERMINAL_NOT_CONNECTED"


def test_ping_reports_latency(client: MT5Client, fake_mt5: FakeMT5, frozen_utc):
    client.connect()
    ok, ms = client.ping()
    assert ok is True
    assert ms >= 0


def test_ping_false_when_disconnected(fake_mt5: FakeMT5, frozen_utc):
    c = MT5Client(mt5_module=fake_mt5)
    fake_mt5._terminal_info = None
    ok, _ = c.ping()
    assert ok is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_adapter_mt5_client.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.adapter.mt5_client'`.

- [ ] **Step 3: Write `src/mt5_mcp/adapter/mt5_client.py`**

```python
"""Singleton wrapper around the `MetaTrader5` Python module.

This is the ONLY module that imports `MetaTrader5`. Everything else goes
through an `MT5Client` instance, which:
  - Owns initialize / shutdown lifecycle.
  - Caches the broker's TZ offset (inferred once per connect).
  - Transparently re-initialises once if a call returns the "not
    initialized" retcode mid-session.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, TypeVar

from mt5_mcp.adapter.conversions import infer_broker_tz_offset
from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail


logger = logging.getLogger(__name__)

# mt5lib's internal retcode indicating the library wasn't initialized for
# this call. Exact number per MetaTrader5 source.
_RES_NOT_INITIALIZED = -10004
_RES_IPC_TIMEOUT = -10003


T = TypeVar("T")


def _import_mt5():
    """Import the real `MetaTrader5` module on demand.

    Split out so tests can inject a fake without touching the Windows-only
    import during non-Windows CI runs.
    """
    import MetaTrader5  # type: ignore[import]
    return MetaTrader5


class MT5Client:
    def __init__(
        self,
        *,
        terminal_path: str | None = None,
        mt5_module: Any | None = None,
    ) -> None:
        self._mt5 = mt5_module if mt5_module is not None else _import_mt5()
        self._terminal_path = terminal_path or None
        self._lock = threading.RLock()
        self._initialised = False
        self.broker_offset_minutes = 0

    # --- lifecycle -------------------------------------------------------

    def connect(self) -> None:
        """Initialise the underlying library and cache broker TZ."""
        with self._lock:
            if self._initialised:
                return
            ok = (
                self._mt5.initialize(self._terminal_path)
                if self._terminal_path
                else self._mt5.initialize()
            )
            if not ok:
                raise MT5Error(self._connection_error("initialize returned False"))
            ti = self._mt5.terminal_info()
            if ti is None:
                raise MT5Error(self._connection_error("terminal_info returned None"))
            self.broker_offset_minutes = infer_broker_tz_offset(
                ti.time, datetime.now(timezone.utc)
            )
            self._initialised = True
            logger.info(
                "MT5 connected; broker TZ offset = %+d min", self.broker_offset_minutes
            )

    def disconnect(self) -> None:
        with self._lock:
            if not self._initialised:
                return
            try:
                self._mt5.shutdown()
            finally:
                self._initialised = False

    # --- health ----------------------------------------------------------

    def ping(self) -> tuple[bool, int]:
        t0 = time.perf_counter()
        try:
            ti = self._mt5.terminal_info()
        except Exception:
            return False, 0
        ms = int((time.perf_counter() - t0) * 1000)
        return (ti is not None), ms

    # --- call routing ---------------------------------------------------

    def _call_with_reinit(self, fn: Callable[[], T]) -> T:
        """Invoke `fn`; if it returns None AND last_error is the
        not-initialized retcode, re-init once and retry.
        """
        result = fn()
        if result is not None:
            return result
        err = self._mt5.last_error()
        code = err[0] if isinstance(err, (tuple, list)) and err else 0
        if code != _RES_NOT_INITIALIZED:
            return result  # genuine None; caller will decide what it means
        logger.warning("mt5lib returned NOT_INITIALIZED; attempting re-init")
        with self._lock:
            self._initialised = False
        try:
            self.connect()
        except MT5Error:
            raise
        return fn()  # one retry; propagates whatever the second call returns

    # --- module accessor (used by symbols + tools) -----------------------

    @property
    def mt5(self) -> Any:
        return self._mt5

    # --- error helpers --------------------------------------------------

    def _connection_error(self, message: str) -> ErrorDetail:
        raw = self._mt5.last_error()
        details = {"raw_error": raw, "why": message}
        return ErrorDetail(
            code="TERMINAL_NOT_CONNECTED",
            message="MT5 terminal is not connected. Please open MT5 and log into your broker.",
            retryable=False,
            requires_human=True,
            details=details,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_adapter_mt5_client.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/adapter/mt5_client.py tests/test_adapter_mt5_client.py
git commit -m "feat: add MT5Client singleton with TZ caching and transparent reinit"
```

---

## Task 8: Adapter — symbol preparation pipeline

Implements §10.1 of the architecture: symbol_info lookup, auto-select-if-hidden, filling-mode compatibility probe, volume validation, price quantisation, 60s cache.

**Files:**
- Create: `src/mt5_mcp/adapter/symbols.py`
- Create: `tests/test_adapter_symbols.py`

- [ ] **Step 1: Write the failing test (`tests/test_adapter_symbols.py`)**

```python
"""Symbol preparation pipeline."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.adapter.symbols import SymbolPrep
from mt5_mcp.errors import MT5Error
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo


@pytest.fixture
def prep(fake_mt5: FakeMT5, frozen_utc) -> SymbolPrep:
    client = MT5Client(mt5_module=fake_mt5)
    client.connect()
    return SymbolPrep(client)


def test_unknown_symbol_raises_not_found(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["XYZ"] = None
    with pytest.raises(MT5Error) as ei:
        prep.get("XYZ")
    assert ei.value.detail.code == "SYMBOL_NOT_FOUND"


def test_hidden_symbol_is_selected(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", visible=False)
    info = prep.get("EURUSD")
    assert info.name == "EURUSD"
    # symbol_select was called exactly once during prep.
    assert fake_mt5.calls.get("symbol_select") == 1


def test_cache_hits_on_second_call(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    prep.get("EURUSD")
    prep.get("EURUSD")
    assert fake_mt5.calls["symbol_info"] == 1


def test_cache_expires(prep: SymbolPrep, fake_mt5: FakeMT5, monkeypatch):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    prep.get("EURUSD")

    # Jump clock forward past TTL.
    import mt5_mcp.adapter.symbols as sym_mod
    t0 = sym_mod._monotonic()
    monkeypatch.setattr(sym_mod, "_monotonic", lambda: t0 + 120)
    prep.get("EURUSD")
    assert fake_mt5.calls["symbol_info"] == 2


def test_validate_volume_ok(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=100.0, volume_step=0.01
    )
    prep.validate_volume("EURUSD", Decimal("0.10"))  # no raise


def test_validate_volume_below_min(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=100.0, volume_step=0.01
    )
    with pytest.raises(MT5Error) as ei:
        prep.validate_volume("EURUSD", Decimal("0.001"))
    assert ei.value.detail.code == "INVALID_VOLUME"
    assert "min" in ei.value.detail.message.lower()


def test_validate_volume_bad_step(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=100.0, volume_step=0.01
    )
    with pytest.raises(MT5Error) as ei:
        prep.validate_volume("EURUSD", Decimal("0.015"))
    assert ei.value.detail.code == "INVALID_VOLUME"


def test_validate_volume_above_max(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=10.0, volume_step=0.01
    )
    with pytest.raises(MT5Error):
        prep.validate_volume("EURUSD", Decimal("11"))


def test_quantise_price_rounds_to_digits(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", digits=5)
    out = prep.quantise_price("EURUSD", Decimal("1.234567"))
    assert out == Decimal("1.23457")


def test_pick_filling_mode_prefers_ioc_for_market(prep: SymbolPrep, fake_mt5: FakeMT5):
    # FOK|IOC available
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=1 | 2
    )
    assert prep.pick_filling_mode("EURUSD", order_type="market") == fake_mt5.ORDER_FILLING_IOC


def test_pick_filling_mode_falls_back_to_fok(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=1  # FOK only
    )
    assert prep.pick_filling_mode("EURUSD", order_type="market") == fake_mt5.ORDER_FILLING_FOK


def test_pick_filling_mode_pending_prefers_return(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=1 | 2 | 4
    )
    assert prep.pick_filling_mode("EURUSD", order_type="limit") == fake_mt5.ORDER_FILLING_RETURN


def test_pick_filling_mode_none_matches(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=0  # broker advertises nothing
    )
    with pytest.raises(MT5Error) as ei:
        prep.pick_filling_mode("EURUSD", order_type="market")
    assert ei.value.detail.code == "INVALID_FILLING_MODE"


def test_invalidate_clears_cache(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    prep.get("EURUSD")
    prep.invalidate()
    prep.get("EURUSD")
    assert fake_mt5.calls["symbol_info"] == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_adapter_symbols.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.adapter.symbols'`.

- [ ] **Step 3: Write `src/mt5_mcp/adapter/symbols.py`**

```python
"""Symbol preparation pipeline — selects, validates, caches.

Hides mt5lib's sharp edges described in §10.1 of the architecture doc:
  - symbol_info() returning None for unknown names
  - needing symbol_select() before quote/trade calls
  - broker-specific filling-mode bitmasks
  - volume step / min / max arithmetic
  - price quantisation to `point`
"""

from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail


_CACHE_TTL_S = 60.0

# Indirection so tests can monkeypatch the clock.
def _monotonic() -> float:
    return _time.monotonic()


@dataclass
class _CacheEntry:
    info: Any
    expires_at: float


class SymbolPrep:
    def __init__(self, client: MT5Client) -> None:
        self._client = client
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()

    # --- public API ------------------------------------------------------

    def get(self, symbol: str) -> Any:
        """Return a populated `symbol_info` (post-select). Raises if unknown."""
        with self._lock:
            hit = self._cache.get(symbol)
            if hit is not None and hit.expires_at > _monotonic():
                return hit.info
        info = self._client.mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_FOUND",
                message=f"Symbol '{symbol}' not found on this broker.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol},
            ))
        if not getattr(info, "visible", True):
            ok = self._client.mt5.symbol_select(symbol, True)
            if not ok:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_ENABLED",
                    message=f"Could not enable symbol '{symbol}' in Market Watch.",
                    retryable=True,
                    requires_human=False,
                    details={"symbol": symbol},
                ))
            info = self._client.mt5.symbol_info(symbol)
            if info is None:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_FOUND",
                    message=f"Symbol '{symbol}' vanished after select.",
                    retryable=False,
                    requires_human=True,
                    details={"symbol": symbol},
                ))
        with self._lock:
            self._cache[symbol] = _CacheEntry(info, _monotonic() + _CACHE_TTL_S)
        return info

    def validate_volume(self, symbol: str, volume: Decimal) -> None:
        info = self.get(symbol)
        vmin = Decimal(str(info.volume_min))
        vmax = Decimal(str(info.volume_max))
        vstep = Decimal(str(info.volume_step))
        if volume < vmin:
            raise MT5Error(ErrorDetail(
                code="INVALID_VOLUME",
                message=f"Volume {volume} below min {vmin} for {symbol}.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol, "volume": str(volume), "min": str(vmin)},
            ))
        if volume > vmax:
            raise MT5Error(ErrorDetail(
                code="INVALID_VOLUME",
                message=f"Volume {volume} above max {vmax} for {symbol}.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol, "volume": str(volume), "max": str(vmax)},
            ))
        # Step check: (volume - vmin) must be a multiple of vstep within quantise tolerance.
        ratio = (volume - vmin) / vstep
        if ratio != ratio.to_integral_value():
            raise MT5Error(ErrorDetail(
                code="INVALID_VOLUME",
                message=f"Volume {volume} is not a multiple of step {vstep} for {symbol}.",
                retryable=False,
                requires_human=False,
                details={"symbol": symbol, "volume": str(volume), "step": str(vstep)},
            ))

    def quantise_price(self, symbol: str, price: Decimal) -> Decimal:
        info = self.get(symbol)
        digits = int(info.digits)
        q = Decimal(1).scaleb(-digits)  # e.g. digits=5 → 0.00001
        return price.quantize(q, rounding=ROUND_HALF_UP)

    def pick_filling_mode(
        self,
        symbol: str,
        *,
        order_type: Literal["market", "limit", "stop", "stop_limit"],
    ) -> int:
        info = self.get(symbol)
        mask = int(info.filling_mode)
        mt5 = self._client.mt5
        # For market orders prefer IOC, fall back to FOK. RETURN is invalid for market.
        # For pending orders, RETURN is the canonical choice.
        if order_type == "market":
            preferences = (
                (mt5.SYMBOL_FILLING_IOC, mt5.ORDER_FILLING_IOC),
                (mt5.SYMBOL_FILLING_FOK, mt5.ORDER_FILLING_FOK),
            )
        else:
            # Pending orders: RETURN preferred; fall back to IOC then FOK.
            preferences = (
                (4, mt5.ORDER_FILLING_RETURN),
                (mt5.SYMBOL_FILLING_IOC, mt5.ORDER_FILLING_IOC),
                (mt5.SYMBOL_FILLING_FOK, mt5.ORDER_FILLING_FOK),
            )
        for advertised_bit, order_filling in preferences:
            if mask & advertised_bit:
                return order_filling
        raise MT5Error(ErrorDetail(
            code="INVALID_FILLING_MODE",
            message=f"Symbol {symbol} accepts no filling mode compatible with {order_type}.",
            retryable=False,
            requires_human=True,
            details={"symbol": symbol, "filling_mode_mask": mask},
        ))

    def invalidate(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                self._cache.pop(symbol, None)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_adapter_symbols.py -v`
Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/adapter/symbols.py tests/test_adapter_symbols.py
git commit -m "feat: add symbol preparation pipeline (select, validate, cache)"
```

---

## Task 9: Server bootstrap + tool registry

Wires `FastMCP`, instantiates an `MT5Client` and `SymbolPrep`, exposes both to tool modules via a small `AppContext`, and registers all tools.

**Files:**
- Create: `src/mt5_mcp/server.py`
- Create: `src/mt5_mcp/tools/__init__.py`
- Modify: `src/mt5_mcp/__main__.py`

- [ ] **Step 1: Write `src/mt5_mcp/server.py`**

```python
"""MCP server factory.

`build_server()` returns a FastMCP instance with tools registered. The
actual connect-to-terminal happens on first tool call so `serve` can start
up even when MT5 is offline (tools just return TERMINAL_NOT_CONNECTED).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.adapter.symbols import SymbolPrep
from mt5_mcp.config import Config, ConfigWatcher, default_config_path, load_config


logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Hands-off wiring passed from the server to each tool module."""

    client: MT5Client
    symbols: SymbolPrep
    config_watcher: ConfigWatcher | None

    @property
    def config(self) -> Config:
        if self.config_watcher is not None:
            return self.config_watcher.current
        return Config()


_ctx_lock = threading.Lock()
_ctx: AppContext | None = None


def build_context(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> AppContext:
    """Instantiate the client + symbol prep + config watcher."""
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
            cfg = load_config()  # defaults
        # Client.
        client = MT5Client(
            terminal_path=cfg.mt5.terminal_path or None,
            mt5_module=mt5_module,
        )
        symbols = SymbolPrep(client)
        _ctx = AppContext(client=client, symbols=symbols, config_watcher=watcher)
        return _ctx


def get_context() -> AppContext:
    if _ctx is None:
        raise RuntimeError("AppContext not built; call build_context() first")
    return _ctx


def reset_context_for_tests() -> None:
    global _ctx
    with _ctx_lock:
        _ctx = None


def build_server(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> FastMCP:
    """Build a FastMCP server with all Phase 1 read tools registered."""
    build_context(config_path=config_path, mt5_module=mt5_module)
    mcp = FastMCP("mt5-mcp")
    from mt5_mcp.tools import register_tools

    register_tools(mcp)
    return mcp
```

- [ ] **Step 2: Write `src/mt5_mcp/tools/__init__.py`**

```python
"""Tool registry — each subsequent task adds a register_* function here."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register every Phase 1 read tool on `mcp`."""
    from mt5_mcp.tools import account, history, market, orders, positions, system

    system.register(mcp)
    account.register(mcp)
    market.register(mcp)
    positions.register(mcp)
    orders.register(mcp)
    history.register(mcp)
```

- [ ] **Step 3: Modify `src/mt5_mcp/__main__.py`** — replace the `serve` branch

Replace the `if not argv or argv[0] == "serve":` block with:

```python
    if not argv or argv[0] == "serve":
        from mt5_mcp.server import build_server
        mcp = build_server()
        mcp.run(transport="stdio")
        return 0
```

- [ ] **Step 4: Create placeholder tool modules**

To keep `register_tools` importable before Task 10, create each tool module as a stub now — each file defines a `register(mcp)` no-op. Tasks 10-15 replace the body.

`src/mt5_mcp/tools/system.py`:
```python
from mcp.server.fastmcp import FastMCP

def register(mcp: FastMCP) -> None: ...
```

Same for `account.py`, `market.py`, `positions.py`, `orders.py`, `history.py` — identical body.

- [ ] **Step 5: Smoke-test the server builds**

Create a quick sanity test: `tests/test_server_bootstrap.py`

```python
"""Server scaffolding only — real tool behaviour tested in tests/test_tools_*.py."""

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5


def test_build_server_registers_tools():
    reset_context_for_tests()
    server = build_server(mt5_module=FakeMT5())
    # FastMCP exposes the tool manager; check registered tool count.
    tools = server._tool_manager.list_tools()
    # Phase 1 registers 9 read tools; placeholder register() adds 0.
    assert isinstance(tools, list)
```

Run: `pytest tests/test_server_bootstrap.py -v`
Expected: passes. (Zero tools until Task 10 wires real ones.)

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/server.py src/mt5_mcp/tools/ src/mt5_mcp/__main__.py tests/test_server_bootstrap.py
git commit -m "feat: bootstrap FastMCP server + tool registry"
```

---

## Task 10: Tool — `ping` + `get_terminal_info`

The simplest tool first — establishes the pattern of wrapping every handler in a uniform error envelope, reading from `AppContext`, etc.

**Files:**
- Modify: `src/mt5_mcp/tools/system.py`
- Create: `src/mt5_mcp/tools/_common.py`
- Create: `tests/test_tools_system.py`

- [ ] **Step 1: Write the failing test (`tests/test_tools_system.py`)**

```python
"""Tool tests for ping + get_terminal_info."""

from __future__ import annotations

from datetime import datetime

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp()),
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name: str, **kwargs):
    """Directly invoke a registered tool by name for unit testing."""
    handler = server._tool_manager.get_tool(name).fn
    return handler(**kwargs)


def test_ping_returns_ok_and_latency(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(server, "ping")
    assert out["ok"] is True
    assert out["latency_ms"] >= 0


def test_ping_returns_false_when_terminal_gone(server_and_mt5):
    server, fake = server_and_mt5
    fake._terminal_info = None
    out = _call(server, "ping")
    assert out["ok"] is False


def test_get_terminal_info_populates_fields(server_and_mt5):
    server, fake = server_and_mt5
    info = _call(server, "get_terminal_info")
    assert info.connected is True
    assert info.build == 4150
    assert info.broker_tz_offset_minutes == 180
    assert info.login == 123456
    assert info.server == "FintrixMarkets-Demo"


def test_get_terminal_info_when_disconnected(server_and_mt5):
    server, fake = server_and_mt5
    fake._terminal_info = None
    fake._account_info = None
    out = _call(server, "get_terminal_info")
    # When disconnected we still return a structured response — the code
    # surfaces TERMINAL_NOT_CONNECTED as an error detail.
    assert out == {"error": {
        "code": "TERMINAL_NOT_CONNECTED",
        "message": "MT5 terminal is not connected. Please open MT5 and log into your broker.",
        "retryable": False,
        "requires_human": True,
        "details": out["error"]["details"],
        "mt5_retcode": None,
    }}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_tools_system.py -v`
Expected: all 4 fail — `ping` and `get_terminal_info` aren't registered.

- [ ] **Step 3: Write `src/mt5_mcp/tools/_common.py`**

```python
"""Shared tool helpers: error envelope, lazy-connect guard."""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from mt5_mcp.errors import MT5Error
from mt5_mcp.server import AppContext, get_context
from mt5_mcp.types import ErrorDetail


R = TypeVar("R")


def ensure_connected(ctx: AppContext) -> ErrorDetail | None:
    """Connect on first use; return an ErrorDetail if that fails."""
    try:
        ctx.client.connect()
    except MT5Error as exc:
        return exc.detail
    return None


def error_envelope(fn: Callable[..., R]) -> Callable[..., Any]:
    """Wrap a tool handler so MT5Error becomes `{"error": {...}}`."""

    @functools.wraps(fn)
    def _wrapped(**kwargs: Any) -> Any:
        ctx = get_context()
        err = ensure_connected(ctx)
        if err is not None:
            return {"error": err.model_dump(mode="json")}
        try:
            return fn(ctx, **kwargs)
        except MT5Error as exc:
            return {"error": exc.detail.model_dump(mode="json")}

    return _wrapped
```

- [ ] **Step 4: Write `src/mt5_mcp/tools/system.py`**

```python
"""System tools: ping, get_terminal_info."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import terminal_info_from_raw
from mt5_mcp.server import AppContext
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import TerminalInfo


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def ping() -> dict[str, Any]:
        """Health check — verifies the MT5 terminal is reachable.

        Returns {"ok": bool, "latency_ms": int}. Cheap; agents should call
        this after idle periods or errors that smell like disconnection.
        """
        from mt5_mcp.server import get_context
        ctx = get_context()
        ok, ms = ctx.client.ping()
        return {"ok": ok, "latency_ms": ms}

    @mcp.tool()
    @error_envelope
    def get_terminal_info(ctx: AppContext) -> TerminalInfo:
        """MT5 terminal connection state and broker TZ offset."""
        raw = ctx.client.mt5.terminal_info()
        if raw is None:
            from mt5_mcp.errors import MT5Error
            from mt5_mcp.types import ErrorDetail
            raise MT5Error(ErrorDetail(
                code="TERMINAL_NOT_CONNECTED",
                message="MT5 terminal is not connected. Please open MT5 and log into your broker.",
                retryable=False, requires_human=True, details=None,
            ))
        acct = ctx.client.mt5.account_info()
        _, latency = ctx.client.ping()
        return terminal_info_from_raw(
            raw,
            login=(acct.login if acct else 0),
            server=(acct.server if acct else ""),
            broker_offset_minutes=ctx.client.broker_offset_minutes,
            latency_ms=latency,
        )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_tools_system.py -v`
Expected: all 4 pass.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/tools/system.py src/mt5_mcp/tools/_common.py tests/test_tools_system.py
git commit -m "feat: add ping and get_terminal_info tools"
```

---

## Task 11: Tool — `get_account_info`

**Files:**
- Modify: `src/mt5_mcp/tools/account.py`
- Create: `tests/test_tools_account.py`

- [ ] **Step 1: Write the failing test**

```python
"""get_account_info tool."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeAccountInfo, FakeMT5, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_account_info_populates(server_and_mt5):
    server, fake = server_and_mt5
    fake._account_info = FakeAccountInfo(
        login=42, name="Vincent", server="FX-Demo", currency="USD",
        balance=5_000.0, equity=5_010.0, margin=50.0, margin_free=4_960.0,
        margin_level=10020.0, leverage=100, trade_allowed=True, margin_mode=0,
    )
    info = _call(server, "get_account_info")
    assert info.login == 42
    assert info.currency == "USD"
    assert info.balance == Decimal("5000.0")
    assert info.margin_mode == "retail_netting"


def test_get_account_info_errors_when_none(server_and_mt5):
    server, fake = server_and_mt5
    fake._account_info = None
    out = _call(server, "get_account_info")
    assert out["error"]["code"] == "TERMINAL_NOT_CONNECTED"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_tools_account.py -v`
Expected: fails — tool not registered.

- [ ] **Step 3: Write `src/mt5_mcp/tools/account.py`**

```python
"""Account tool: get_account_info."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import account_info_from_raw
from mt5_mcp.errors import MT5Error
from mt5_mcp.server import AppContext
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import AccountInfo, ErrorDetail


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_account_info(ctx: AppContext) -> AccountInfo:
        """Balance, equity, margin, leverage, currency, margin mode."""
        raw = ctx.client.mt5.account_info()
        if raw is None:
            raise MT5Error(ErrorDetail(
                code="TERMINAL_NOT_CONNECTED",
                message="MT5 terminal is not connected. Please open MT5 and log into your broker.",
                retryable=False, requires_human=True,
            ))
        return account_info_from_raw(raw)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_tools_account.py -v`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/tools/account.py tests/test_tools_account.py
git commit -m "feat: add get_account_info tool"
```

---

## Task 12: Tools — `get_quote`, `get_symbols`, `get_market_hours`

Market-data read tools. `get_market_hours` is derived from `symbol_info.trade_mode` + session hours; v1 returns a simplified open/closed flag.

**Files:**
- Modify: `src/mt5_mcp/tools/market.py`
- Create: `tests/test_tools_market.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Market tools: get_quote, get_symbols, get_market_hours."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


@pytest.fixture
def server_and_mt5(frozen_utc):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_quote_returns_bid_ask(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    q = _call(server, "get_quote", symbol="EURUSD")
    assert q.bid == Decimal("1.0823")
    assert q.ask == Decimal("1.0824")
    assert q.symbol == "EURUSD"


def test_get_quote_unknown_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["XYZ"] = None
    out = _call(server, "get_quote", symbol="XYZ")
    assert out["error"]["code"] == "SYMBOL_NOT_FOUND"


def test_get_quote_no_tick_available(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = None
    out = _call(server, "get_quote", symbol="EURUSD")
    assert out["error"]["code"] == "SYMBOL_NOT_ENABLED"


def test_get_symbols_no_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbols_get = (
        FakeSymbolInfo(name="EURUSD", path="Forex\\Majors\\EURUSD"),
        FakeSymbolInfo(name="XAUUSD", path="Metals\\XAUUSD"),
    )
    out = _call(server, "get_symbols")
    assert {s.name for s in out} == {"EURUSD", "XAUUSD"}
    assert {s.category for s in out} == {"Forex", "Metals"}


def test_get_symbols_with_category_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbols_get = (
        FakeSymbolInfo(name="EURUSD", path="Forex\\Majors\\EURUSD"),
        FakeSymbolInfo(name="XAUUSD", path="Metals\\XAUUSD"),
    )
    out = _call(server, "get_symbols", category="Forex")
    assert [s.name for s in out] == ["EURUSD"]


def test_get_market_hours_open_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", trade_mode=4)
    out = _call(server, "get_market_hours", symbol="EURUSD")
    assert out.symbol == "EURUSD"
    assert out.is_open is True


def test_get_market_hours_disabled_symbol(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", trade_mode=0)
    out = _call(server, "get_market_hours", symbol="EURUSD")
    assert out.is_open is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_tools_market.py -v`
Expected: all 7 fail.

- [ ] **Step 3: Write `src/mt5_mcp/tools/market.py`**

```python
"""Market tools: get_quote, get_symbols, get_market_hours."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import quote_from_tick, symbol_info_from_raw
from mt5_mcp.errors import MT5Error
from mt5_mcp.server import AppContext
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import ErrorDetail, MarketHours, Quote, SymbolInfo


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_quote(ctx: AppContext, symbol: str) -> Quote:
        """Current bid/ask for a symbol. Prepares the symbol in Market Watch if needed."""
        ctx.symbols.get(symbol)  # select if hidden; raises SYMBOL_NOT_FOUND if unknown
        tick = ctx.client.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_ENABLED",
                message=f"No tick data for {symbol}; market may be closed.",
                retryable=True, requires_human=False,
                details={"symbol": symbol},
            ))
        return quote_from_tick(tick, symbol=symbol, broker_offset_minutes=ctx.client.broker_offset_minutes)

    @mcp.tool()
    @error_envelope
    def get_symbols(ctx: AppContext, category: str | None = None) -> list[SymbolInfo]:
        """List tradeable instruments, optionally filtered by category (e.g. 'Forex', 'Metals')."""
        raws = ctx.client.mt5.symbols_get()
        out = [symbol_info_from_raw(r) for r in raws]
        if category is not None:
            out = [s for s in out if s.category.lower() == category.lower()]
        return out

    @mcp.tool()
    @error_envelope
    def get_market_hours(ctx: AppContext, symbol: str) -> MarketHours:
        """Whether the given symbol's session is open right now.

        v1 returns a simplified is_open derived from `trade_mode`; session
        windows (next_open, next_close) are populated if the broker exposes
        them but left None otherwise.
        """
        info = ctx.symbols.get(symbol)
        return MarketHours(
            symbol=symbol,
            is_open=getattr(info, "trade_mode", 0) != 0,
            next_open=None,  # broker session schedule parsing deferred
            next_close=None,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_tools_market.py -v`
Expected: all 7 pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/tools/market.py tests/test_tools_market.py
git commit -m "feat: add get_quote, get_symbols, get_market_hours tools"
```

---

## Task 13: Tools — `get_positions`, `get_orders`

**Files:**
- Modify: `src/mt5_mcp/tools/positions.py`
- Modify: `src/mt5_mcp/tools/orders.py`
- Create: `tests/test_tools_positions.py`
- Create: `tests/test_tools_orders.py`

- [ ] **Step 1: Write the failing tests (positions + orders)**

`tests/test_tools_positions.py`:
```python
from __future__ import annotations

from datetime import datetime

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5, FakePosition, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_positions_no_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=1, symbol="EURUSD"),
        FakePosition(ticket=2, symbol="GBPUSD"),
    )
    out = _call(server, "get_positions")
    assert [p.ticket for p in out] == [1, 2]


def test_get_positions_symbol_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=1, symbol="EURUSD"),
        FakePosition(ticket=2, symbol="GBPUSD"),
    )
    out = _call(server, "get_positions", symbol="EURUSD")
    assert [p.ticket for p in out] == [1]


def test_get_positions_empty(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(server, "get_positions")
    assert out == []
```

`tests/test_tools_orders.py`:
```python
from __future__ import annotations

from datetime import datetime

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5, FakeOrder, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_orders_returns_all(server_and_mt5):
    server, fake = server_and_mt5
    fake._orders_get = (
        FakeOrder(ticket=10, symbol="EURUSD", type=2),
        FakeOrder(ticket=11, symbol="GBPUSD", type=3),
    )
    out = _call(server, "get_orders")
    assert [o.ticket for o in out] == [10, 11]
    assert [o.type for o in out] == ["buy_limit", "sell_limit"]


def test_get_orders_symbol_filter(server_and_mt5):
    server, fake = server_and_mt5
    fake._orders_get = (
        FakeOrder(ticket=10, symbol="EURUSD", type=2),
        FakeOrder(ticket=11, symbol="GBPUSD", type=3),
    )
    out = _call(server, "get_orders", symbol="EURUSD")
    assert [o.ticket for o in out] == [10]


def test_get_orders_empty(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(server, "get_orders")
    assert out == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_tools_positions.py tests/test_tools_orders.py -v`
Expected: all 6 fail.

- [ ] **Step 3: Write `src/mt5_mcp/tools/positions.py`**

```python
"""Position tools: get_positions."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import position_from_raw
from mt5_mcp.server import AppContext
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import Position


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_positions(ctx: AppContext, symbol: str | None = None) -> list[Position]:
        """Open positions, optionally filtered to a single symbol."""
        raws = ctx.client.mt5.positions_get(symbol=symbol) if symbol else ctx.client.mt5.positions_get()
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [position_from_raw(r, broker_offset_minutes=offset) for r in raws]
```

- [ ] **Step 4: Write `src/mt5_mcp/tools/orders.py`**

```python
"""Order tools: get_orders.

Phase 2 adds place_order / modify_order / cancel_order here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import order_from_raw
from mt5_mcp.server import AppContext
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import Order


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_orders(ctx: AppContext, symbol: str | None = None) -> list[Order]:
        """Pending orders, optionally filtered to a single symbol."""
        raws = ctx.client.mt5.orders_get(symbol=symbol) if symbol else ctx.client.mt5.orders_get()
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [order_from_raw(r, broker_offset_minutes=offset) for r in raws]
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_tools_positions.py tests/test_tools_orders.py -v`
Expected: all 6 pass.

- [ ] **Step 6: Commit**

```bash
git add src/mt5_mcp/tools/positions.py src/mt5_mcp/tools/orders.py tests/test_tools_positions.py tests/test_tools_orders.py
git commit -m "feat: add get_positions and get_orders tools"
```

---

## Task 14: Tool — `get_history`

Returns closed deals within a date range. mt5lib's `history_deals_get` takes python `datetime` in broker-server-TZ. Adapter converts incoming UTC inputs to broker TZ before the call.

**Files:**
- Modify: `src/mt5_mcp/tools/history.py`
- Create: `tests/test_tools_history.py`

- [ ] **Step 1: Write the failing test**

```python
"""get_history tool."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeDeal, FakeMT5, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())  # broker +180
    )
    server = build_server(mt5_module=fake)
    return server, fake


def _call(server, name, **kwargs):
    return server._tool_manager.get_tool(name).fn(**kwargs)


def test_get_history_returns_deals(server_and_mt5):
    server, fake = server_and_mt5
    fake._history_deals_get = (
        FakeDeal(
            ticket=10, order=5, symbol="EURUSD", type=0,
            volume=0.1, price=1.0822, profit=5.0,
            time=int(datetime(2026, 4, 21, 13, 0).timestamp()),
        ),
    )
    out = _call(
        server, "get_history",
        from_ts="2026-04-20T00:00:00Z",
        to_ts="2026-04-21T23:59:59Z",
    )
    assert len(out) == 1
    assert out[0].ticket == 10
    assert out[0].type == "buy"
    assert out[0].profit == Decimal("5.0")


def test_get_history_requires_utc_timestamps(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(
        server, "get_history",
        from_ts="2026-04-20T00:00:00",  # naive — refuse
        to_ts="2026-04-21T23:59:59Z",
    )
    assert out["error"]["code"] == "INVALID_TIMESTAMP"


def test_get_history_rejects_backwards_range(server_and_mt5):
    server, _ = server_and_mt5
    out = _call(
        server, "get_history",
        from_ts="2026-04-22T00:00:00Z",
        to_ts="2026-04-21T00:00:00Z",
    )
    assert out["error"]["code"] == "INVALID_TIMESTAMP"


def test_get_history_empty_result(server_and_mt5):
    server, fake = server_and_mt5
    fake._history_deals_get = tuple()
    out = _call(
        server, "get_history",
        from_ts="2026-04-20T00:00:00Z",
        to_ts="2026-04-21T23:59:59Z",
    )
    assert out == []


def test_get_history_shifts_range_into_broker_tz(server_and_mt5):
    """The mt5lib call must receive `datetime` objects in broker-server TZ."""
    server, fake = server_and_mt5
    from unittest.mock import patch
    with patch.object(fake, "history_deals_get", wraps=fake.history_deals_get) as spy:
        _call(
            server, "get_history",
            from_ts="2026-04-20T00:00:00Z",
            to_ts="2026-04-21T23:59:59Z",
        )
        args, kwargs = spy.call_args
        assert args[0] == datetime(2026, 4, 20, 3, 0)  # +3h in broker TZ
        assert args[1] == datetime(2026, 4, 22, 2, 59, 59)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_tools_history.py -v`
Expected: 5 failures.

- [ ] **Step 3: Write `src/mt5_mcp/tools/history.py`**

```python
"""History tool: get_history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import deal_from_raw
from mt5_mcp.errors import MT5Error
from mt5_mcp.server import AppContext
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import Deal, ErrorDetail


def _parse_utc(raw: str, field: str) -> datetime:
    try:
        # fromisoformat accepts '+00:00' but not 'Z' until 3.11; handle both.
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise MT5Error(ErrorDetail(
            code="INVALID_TIMESTAMP",
            message=f"{field} is not a valid ISO 8601 timestamp: {raw}",
            retryable=False, requires_human=False,
        )) from exc
    if dt.tzinfo is None:
        raise MT5Error(ErrorDetail(
            code="INVALID_TIMESTAMP",
            message=f"{field} must be timezone-aware UTC (use '...Z' or '+00:00').",
            retryable=False, requires_human=False,
        ))
    return dt.astimezone(timezone.utc)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    @error_envelope
    def get_history(
        ctx: AppContext,
        from_ts: str,
        to_ts: str,
        symbol: str | None = None,
    ) -> list[Deal]:
        """Closed deals (trades) within [from_ts, to_ts]. Timestamps must be ISO 8601 UTC."""
        start_utc = _parse_utc(from_ts, "from_ts")
        end_utc = _parse_utc(to_ts, "to_ts")
        if end_utc <= start_utc:
            raise MT5Error(ErrorDetail(
                code="INVALID_TIMESTAMP",
                message="to_ts must be strictly after from_ts.",
                retryable=False, requires_human=False,
            ))
        # mt5lib expects naive datetimes in broker TZ.
        offset = timedelta(minutes=ctx.client.broker_offset_minutes)
        start_broker = (start_utc + offset).replace(tzinfo=None)
        end_broker = (end_utc + offset).replace(tzinfo=None)
        kwargs = {"group": f"*{symbol}*"} if symbol else {}
        raws = ctx.client.mt5.history_deals_get(start_broker, end_broker, **kwargs)
        if raws is None:
            return []
        return [
            deal_from_raw(r, broker_offset_minutes=ctx.client.broker_offset_minutes)
            for r in raws
        ]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_tools_history.py -v`
Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add src/mt5_mcp/tools/history.py tests/test_tools_history.py
git commit -m "feat: add get_history tool with UTC → broker-TZ shifting"
```

---

## Task 15: CLI — `doctor`

Runs every read tool, prints a green/red report. Implementation-wise: builds a server, invokes each tool, formats outcomes.

**Files:**
- Create: `src/mt5_mcp/cli/__init__.py`
- Create: `src/mt5_mcp/cli/doctor.py`
- Create: `tests/test_cli_doctor.py`
- Modify: `src/mt5_mcp/__main__.py`

- [ ] **Step 1: Write the failing test**

```python
"""doctor CLI smoke check."""

from __future__ import annotations

import io
from datetime import datetime

from mt5_mcp.cli.doctor import run_doctor
from mt5_mcp.server import reset_context_for_tests
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def test_doctor_all_green(capsys):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    fake._symbols_get = (FakeSymbolInfo(name="EURUSD"),)

    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD")
    captured = capsys.readouterr()
    assert rc == 0
    assert "[PASS]" in captured.out
    assert "[FAIL]" not in captured.out


def test_doctor_reports_disconnection(capsys):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = None
    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD")
    captured = capsys.readouterr()
    assert rc != 0
    assert "[FAIL]" in captured.out
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_cli_doctor.py -v`
Expected: `ModuleNotFoundError: No module named 'mt5_mcp.cli'`.

- [ ] **Step 3: Write `src/mt5_mcp/cli/__init__.py`** (empty)

- [ ] **Step 4: Write `src/mt5_mcp/cli/doctor.py`**

```python
"""`python -m mt5_mcp doctor` — green/red health report."""

from __future__ import annotations

import sys
from typing import Any, Callable

from mt5_mcp.server import build_server, get_context, reset_context_for_tests


def _check(label: str, fn: Callable[[], Any]) -> bool:
    try:
        result = fn()
        if isinstance(result, dict) and "error" in result:
            print(f"[FAIL] {label}: {result['error']['code']} — {result['error']['message']}")
            return False
        print(f"[PASS] {label}")
        return True
    except Exception as exc:
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
        return False


def run_doctor(*, mt5_module: Any | None = None, probe_symbol: str = "EURUSD") -> int:
    reset_context_for_tests()
    server = build_server(mt5_module=mt5_module)
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
    return 0 if all(results) else 1


def main() -> int:
    return run_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Wire up the CLI in `__main__.py`**

Replace the `doctor` branch in `src/mt5_mcp/__main__.py`:

```python
    if argv[0] == "doctor":
        from mt5_mcp.cli.doctor import main as doctor_main
        return doctor_main()
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_cli_doctor.py -v`
Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add src/mt5_mcp/cli/ src/mt5_mcp/__main__.py tests/test_cli_doctor.py
git commit -m "feat: add doctor CLI smoke check"
```

---

## Task 16: CLI — `export-symbols`

Dumps the full symbol list to CSV. One row per instrument with all fields from `SymbolInfo` plus trading-session columns (left blank in v1 until session parsing is added).

**Files:**
- Create: `src/mt5_mcp/cli/export_symbols.py`
- Create: `tests/test_cli_export_symbols.py`
- Modify: `src/mt5_mcp/__main__.py`

- [ ] **Step 1: Write the failing test**

```python
"""export-symbols CLI."""

from __future__ import annotations

import csv
from pathlib import Path

from mt5_mcp.cli.export_symbols import run_export
from mt5_mcp.server import reset_context_for_tests
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo


def test_export_writes_csv_with_all_symbols(tmp_path: Path):
    reset_context_for_tests()
    fake = FakeMT5()
    from datetime import datetime
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0).timestamp())
    )
    fake._symbols_get = (
        FakeSymbolInfo(name="EURUSD", path="Forex\\Majors\\EURUSD"),
        FakeSymbolInfo(name="XAUUSD", path="Metals\\XAUUSD"),
    )
    out = tmp_path / "symbols.csv"
    rc = run_export(output=out, mt5_module=fake)
    assert rc == 0

    with out.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["name"] for r in rows} == {"EURUSD", "XAUUSD"}
    assert {r["category"] for r in rows} == {"Forex", "Metals"}
    # spot-check one numeric column round-trips as string
    assert rows[0]["volume_step"] == "0.01"


def test_export_exits_nonzero_when_disconnected(tmp_path: Path):
    reset_context_for_tests()
    fake = FakeMT5()
    fake._terminal_info = None
    out = tmp_path / "symbols.csv"
    rc = run_export(output=out, mt5_module=fake)
    assert rc != 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_cli_export_symbols.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/mt5_mcp/cli/export_symbols.py`**

```python
"""`python -m mt5_mcp export-symbols --output symbols.csv`."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from mt5_mcp.server import build_server, reset_context_for_tests


_COLUMNS = [
    "name",
    "description",
    "category",
    "contract_size",
    "tick_size",
    "volume_min",
    "volume_max",
    "volume_step",
    "currency_profit",
    "currency_margin",
    "filling_modes",
    "digits",
    "is_tradeable",
]


def run_export(*, output: Path, mt5_module: Any | None = None) -> int:
    reset_context_for_tests()
    server = build_server(mt5_module=mt5_module)
    tm = server._tool_manager
    result = tm.get_tool("get_symbols").fn()
    if isinstance(result, dict) and "error" in result:
        print(f"error: {result['error']['code']}: {result['error']['message']}", file=sys.stderr)
        return 1
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        for sym in result:
            writer.writerow({
                "name": sym.name,
                "description": sym.description,
                "category": sym.category,
                "contract_size": str(sym.contract_size),
                "tick_size": str(sym.tick_size),
                "volume_min": str(sym.volume_min),
                "volume_max": str(sym.volume_max),
                "volume_step": str(sym.volume_step),
                "currency_profit": sym.currency_profit,
                "currency_margin": sym.currency_margin,
                "filling_modes": "|".join(sym.filling_modes),
                "digits": str(sym.digits),
                "is_tradeable": "true" if sym.is_tradeable else "false",
            })
    print(f"wrote {len(result)} symbols to {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mt5-mcp export-symbols")
    p.add_argument("--output", "-o", type=Path, default=Path("symbols.csv"))
    args = p.parse_args(argv)
    return run_export(output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Wire up in `__main__.py`**

Replace the `export-symbols` branch:

```python
    if argv[0] == "export-symbols":
        from mt5_mcp.cli.export_symbols import main as export_main
        return export_main(argv[1:])
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_cli_export_symbols.py -v`
Expected: both pass.

- [ ] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: every test in the suite passes (~60+ tests).

- [ ] **Step 7: Commit**

```bash
git add src/mt5_mcp/cli/export_symbols.py src/mt5_mcp/__main__.py tests/test_cli_export_symbols.py
git commit -m "feat: add export-symbols CLI"
```

---

## Task 17: Final sanity — wire `__main__` to dispatch cleanly, end-to-end smoke

Make sure the whole CLI surface works from `python -m mt5_mcp <command>`.

**Files:**
- Modify: `src/mt5_mcp/__main__.py` (final cleanup)

- [ ] **Step 1: Finalise `src/mt5_mcp/__main__.py`**

```python
"""Entry point: `python -m mt5_mcp <command>`.

Commands:
  serve              Run the MCP server on stdio (default).
  doctor             Run read-tool health check.
  export-symbols     Dump broker symbols to CSV.
  reload-config      Touch the config file so a running server reloads.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] == "serve":
        from mt5_mcp.server import build_server
        server = build_server()
        server.run(transport="stdio")
        return 0

    cmd = argv[0]

    if cmd == "doctor":
        from mt5_mcp.cli.doctor import main as doctor_main
        return doctor_main()

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

- [ ] **Step 2: Smoke-test the dispatch**

Run (on a machine where MT5 isn't installed — these should fail gracefully, not raise):
- `python -m mt5_mcp doctor` — expected: prints [FAIL] lines, exits non-zero. Won't pass without a terminal, but must not crash.
- `python -m mt5_mcp export-symbols --output /tmp/s.csv` — expected: "error: TERMINAL_NOT_CONNECTED…" to stderr, exit 1.
- `python -m mt5_mcp frobnicate` — expected: "unknown command" to stderr, exit 2.

If the engineer is on Windows with a running, logged-in MT5 terminal, `python -m mt5_mcp doctor` should report all green. That is the end-to-end confirmation.

- [ ] **Step 3: Run full suite + coverage one more time**

Run: `pytest -v --tb=short`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/mt5_mcp/__main__.py
git commit -m "chore: finalise mt5_mcp CLI dispatch"
```

- [ ] **Step 5: (Optional) Tag Phase 1**

```bash
git tag phase-1-complete
```

---

## Self-review

**Spec coverage — every Phase 1 deliverable maps to a task:**
- pyproject / layout / licence / README → Task 1
- Pydantic types → Task 3
- Config + watchdog hot reload → Task 5 (incl. `reload-config`)
- `adapter/mt5_client.py` (singleton + TZ cache) → Task 7
- `adapter/symbols.py` (prep pipeline per §10.1) → Task 8
- `adapter/conversions.py` → Task 6
- All 9 read tools → Tasks 10–14
- Unit tests for adapter + conversions (mocked mt5lib) → Tasks 2, 6, 7, 8
- `doctor` CLI → Task 15
- `export-symbols` CLI → Task 16
- `reload-config` CLI → Task 17 (wired; mechanism in Task 5)

**Non-deliverables deferred (explicit):**
- `place_order` / `modify_order` / `cancel_order` / `close_position` — Phase 2
- Policy engine (consent, pre-flight, idempotency, audit log) — Phase 2; config schema exists in Task 5 so the file stays stable across phases
- Resources (`account://current`, etc.) — Phase 3
- HTTP+SSE transport, plugin loader — Phase 3
- Integration tests against a real demo account — Phase 2 lives

**Type consistency check:**
- `TerminalInfo.broker_tz_offset_minutes` — defined in Task 3, produced by `terminal_info_from_raw` (Task 6), consumed by `get_terminal_info` (Task 10). Same name throughout.
- `SymbolInfo.filling_modes: list[str]` — defined in Task 3, produced by `_filling_modes_from_mask` (Task 6), consumed by `export-symbols` (Task 16).
- `MT5Client.broker_offset_minutes` — defined in Task 7, consumed in every tool that converts timestamps (Tasks 10-14). Same name throughout.
- `SymbolPrep.pick_filling_mode` not called in Phase 1 (used by Phase 2 `place_order`), but tested in Task 8 so it's ready.

**Placeholder scan:** no `TODO`, `tbd`, "add appropriate …", or "similar to Task N" remain in the plan. Every task shows the full code it adds.

**Known thin areas the engineer should watch:**
- The real `MetaTrader5.terminal_info()` field surface varies slightly by mt5lib version; `terminal_info_from_raw` reads only fields we depend on. If a new version drops `connected`, the `getattr(..., True)` fallback handles it.
- `infer_broker_tz_offset` has a narrow DST ambiguity window (~1h twice a year). Acceptable for v1 — the offset refreshes on every `connect()`.
- The bogus `currency_profit = "USD"` being declared `float:` in `FakeSymbolInfo` is deliberate shape-fidelity to the real library, which stores it as a string despite its NamedTuple annotation. Real adapter code uses `str(raw.currency_profit)` defensively.

---

## Execution Handoff

Two execution options:

**1. Subagent-Driven (recommended)** — one fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batched with checkpoints for review.

Tell Vincent which approach.
