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


@dataclass
class FakeTerminalInfo:
    connected: bool = True
    trade_allowed: bool = True
    build: int = 4150
    name: str = "MetaTrader 5"
    company: str = "Broker Ltd"
    path: str = "C:/Program Files/MetaTrader 5"
    # Broker-server time as a UNIX epoch treated as naive. See conversions.py.
    time: int = 1_745_000_000


@dataclass
class FakeAccountInfo:
    login: int = 123456
    name: str = "Demo User"
    server: str = "Broker-Demo"
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
    SYMBOL_FILLING_FOK: int = SYMBOL_FILLING_FOK
    SYMBOL_FILLING_IOC: int = SYMBOL_FILLING_IOC
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
    # `order_send_calls` records the request dict passed to each order_send
    # call, in order. Tests use `len()` to count and indexing to inspect.
    order_send_calls: list[dict[str, Any]] = field(default_factory=list)
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

    def order_send(self, request: dict[str, Any]) -> FakeOrderSendResult | None:
        self._bump("order_send")
        # Defensive copy — tests may mutate the dict afterwards.
        self.order_send_calls.append(dict(request))
        return self._order_send

    def last_error(self) -> tuple[int, str]:
        return self._last_error
