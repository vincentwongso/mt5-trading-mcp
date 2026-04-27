"""Tests for the quotes://{symbol} resource read path."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.errors import MT5Error
from mt5_mcp.server import build_server
from mt5_mcp.types import Quote
from tests._resource_helpers import read_resource as _read_resource_raw
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


def _read_resource(server, uri: str) -> Quote:
    """Resolve a FastMCP resource URI and return a parsed Quote."""
    content = _read_resource_raw(server, uri)
    return Quote.model_validate_json(content)


def test_quotes_read_returns_quote(server_and_mt5):
    server, fake = server_and_mt5
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823,
        ask=1.0824,
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
    assert exc_info.value.detail.code == "RESOURCE_NOT_FOUND"
