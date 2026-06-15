"""
FakeMT5 - hand-rolled stand-in for the MetaTrader5 module.

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

# NOTE: SYMBOL_FILLING_* constants are deliberately NOT exposed.
# The real MetaTrader5 Python module does not expose them as module
# attributes either - they're inlined as integer literals in
# `src/mt5_mcp/adapter/symbols.py` (see _SYMBOL_FILLING_FOK/IOC/BOC).
# A v1.0 bug surfaced in Phase 5 because production code was reading
# them from the fake; FakeMT5 must mirror the real module's surface
# exactly so regressions of that shape fail in unit tests.
# Bitmask values, for reference (used by `FakeSymbolInfo.filling_mode`):
#   FOK=1, IOC=2, BOC=4

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8

ORDER_TIME_GTC = 0
ORDER_TIME_SPECIFIED = 2

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7

# mt5lib ENUM_TIMEFRAMES - used by `copy_rates_from_pos`.
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408
TIMEFRAME_W1 = 32769
TIMEFRAME_MN1 = 49153


@dataclass
class FakeTerminalInfo:
    connected: bool = True
    trade_allowed: bool = True
    build: int = 4150
    name: str = "MetaTrader 5"
    company: str = "Example Broker Ltd"
    path: str = "C:/Program Files/MetaTrader 5"
    # Broker-server time as a UNIX epoch treated as naive. See conversions.py.
    time: int = 1_745_000_000


@dataclass
class FakeAccountInfo:
    login: int = 123456
    name: str = "Demo User"
    server: str = "Example-Demo"
    currency: str = "USD"
    balance: float = 10_000.0
    credit: float = 0.0
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
    filling_mode: int = 2 | 1  # IOC | FOK; bit values from MQL5 ENUM_SYMBOL_FILLING_MODE
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
    # Fields surfaced by SymbolInfo enrichment (real mt5lib exposes all of
    # these on `symbol_info()`; they were previously dropped by the adapter).
    trade_calc_mode: int = 0          # 0 = SYMBOL_CALC_MODE_FOREX
    trade_tick_value: float = 1.0
    trade_tick_value_profit: float = 1.0
    trade_tick_value_loss: float = 1.0
    trade_stops_level: int = 0
    trade_freeze_level: int = 0
    margin_initial: float = 0.0
    margin_maintenance: float = 0.0
    margin_hedged: float = 0.0
    swap_long: float = 0.0
    swap_short: float = 0.0
    swap_mode: int = 0                # 0 = SYMBOL_SWAP_MODE_DISABLED
    swap_rollover3days: int = 3       # 3 = Wednesday (FX convention)


@dataclass
class FakeRate:
    """One OHLC row mimicking what `mt5.copy_rates_from_pos` returns.

    The real return is a numpy structured array; this dataclass uses
    attribute access (NamedTuple-like). The `rate_from_raw` converter
    handles both shapes, so tests can pass either."""
    time: int = 1_745_000_000
    open: float = 1.0820
    high: float = 1.0830
    low: float = 1.0815
    close: float = 1.0825
    tick_volume: int = 100
    spread: int = 1
    real_volume: int = 0


@dataclass
class FakeTick:
    time: int = 1_745_000_000
    bid: float = 1.0823
    ask: float = 1.0824
    last: float = 0.0
    volume: int = 0


@dataclass
class FakePosition:
    """Mirrors the real `mt5.TradePosition` named tuple shape - note: NO
    `commission` field. The real MT5 module does not expose commission on
    open positions; it lives on the closing deal (see `FakeDeal`)."""
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
    POSITION_TYPE_BUY: int = POSITION_TYPE_BUY
    POSITION_TYPE_SELL: int = POSITION_TYPE_SELL
    TRADE_ACTION_DEAL: int = TRADE_ACTION_DEAL
    TRADE_ACTION_PENDING: int = TRADE_ACTION_PENDING
    TRADE_ACTION_SLTP: int = TRADE_ACTION_SLTP
    TRADE_ACTION_MODIFY: int = TRADE_ACTION_MODIFY
    TRADE_ACTION_REMOVE: int = TRADE_ACTION_REMOVE
    ORDER_TIME_GTC: int = ORDER_TIME_GTC
    ORDER_TIME_SPECIFIED: int = ORDER_TIME_SPECIFIED
    ORDER_TYPE_BUY: int = ORDER_TYPE_BUY
    ORDER_TYPE_SELL: int = ORDER_TYPE_SELL
    ORDER_TYPE_BUY_LIMIT: int = ORDER_TYPE_BUY_LIMIT
    ORDER_TYPE_SELL_LIMIT: int = ORDER_TYPE_SELL_LIMIT
    ORDER_TYPE_BUY_STOP: int = ORDER_TYPE_BUY_STOP
    ORDER_TYPE_SELL_STOP: int = ORDER_TYPE_SELL_STOP
    ORDER_TYPE_BUY_STOP_LIMIT: int = ORDER_TYPE_BUY_STOP_LIMIT
    ORDER_TYPE_SELL_STOP_LIMIT: int = ORDER_TYPE_SELL_STOP_LIMIT
    TIMEFRAME_M1: int = TIMEFRAME_M1
    TIMEFRAME_M5: int = TIMEFRAME_M5
    TIMEFRAME_M15: int = TIMEFRAME_M15
    TIMEFRAME_M30: int = TIMEFRAME_M30
    TIMEFRAME_H1: int = TIMEFRAME_H1
    TIMEFRAME_H4: int = TIMEFRAME_H4
    TIMEFRAME_D1: int = TIMEFRAME_D1
    TIMEFRAME_W1: int = TIMEFRAME_W1
    TIMEFRAME_MN1: int = TIMEFRAME_MN1

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
    _order_send: FakeOrderSendResult | None = field(default_factory=FakeOrderSendResult)
    # Keyed by (symbol, timeframe) -> tuple of FakeRate. Missing key -> empty tuple.
    _copy_rates_from_pos: dict[tuple[str, int], tuple[FakeRate, ...]] = field(default_factory=dict)
    # Keyed by (symbol, action) where action is ORDER_TYPE_BUY (0) or
    # ORDER_TYPE_SELL (1). Missing key -> 0.0; explicitly setting None means
    # "broker error" and the adapter raises in that case.
    _order_calc_margin: dict[tuple[str, int], float | None] = field(default_factory=dict)
    # `order_send_calls` records the request dict passed to each order_send
    # call, in order. Tests use `len()` to count and indexing to inspect.
    order_send_calls: list[dict[str, Any]] = field(default_factory=list)
    # `initialize_calls` records each initialize() invocation as
    # {"args": (...), "kwargs": {...}} so credential-wiring tests can assert
    # the login/password/server passed through. Records every call, in order.
    initialize_calls: list[dict[str, Any]] = field(default_factory=list)
    _last_error: tuple[int, str] = (0, "")

    # Call-counter bookkeeping - useful for cache-hit assertions.
    calls: dict[str, int] = field(default_factory=dict)

    # --- API surface ---
    def _bump(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def initialize(self, *args: Any, **kwargs: Any) -> bool:
        self._bump("initialize")
        self.initialize_calls.append({"args": args, "kwargs": dict(kwargs)})
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

    def order_send(self, request: dict[str, Any]) -> FakeOrderSendResult | None:
        self._bump("order_send")
        # Defensive copy - tests may mutate the dict afterwards.
        self.order_send_calls.append(dict(request))
        return self._order_send

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> tuple[FakeRate, ...] | None:
        self._bump("copy_rates_from_pos")
        rows = self._copy_rates_from_pos.get((symbol, timeframe))
        if rows is None:
            return None
        # Real mt5lib slices [start_pos : start_pos + count].
        return rows[start_pos : start_pos + count]

    def order_calc_margin(
        self, action: int, symbol: str, volume: float, price: float
    ) -> float | None:
        self._bump("order_calc_margin")
        # `action` in mt5lib: 0 = buy, 1 = sell (re-uses ORDER_TYPE_BUY/SELL).
        key = (symbol, action)
        if key in self._order_calc_margin:
            return self._order_calc_margin[key]
        return 0.0

    def last_error(self) -> tuple[int, str]:
        return self._last_error
