"""Tests for the quotes://{symbol} resource read path."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.errors import MT5Error
from mt5_mcp.server import build_server
from mt5_mcp.types import Quote
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
    """Resolve a FastMCP URI-templated resource and call its handler.

    FastMCP stores templated resources in rm._templates (a dict keyed by
    uri_template string). Each template exposes:
      - template.matches(uri) -> dict of path params, or falsy if no match
      - template.create_resource(uri, params) -> awaitable Resource
      - resource.read() -> awaitable str (JSON serialisation of the return value)

    Implementation notes (verified against installed FastMCP):
    - The handler is called eagerly inside create_resource (not lazily in read).
      Exceptions raised by the handler are wrapped in ValueError by FastMCP.
      We unwrap them here so tests see MT5Error directly.
    - resource.read() returns a JSON string; we parse it back to Quote so
      callers can assert on typed fields.
    """
    rm = server._resource_manager
    for _key, template in rm._templates.items():
        params = template.matches(uri)
        if params:
            try:
                resource = asyncio.run(template.create_resource(uri, params))
            except ValueError as exc:
                # FastMCP wraps handler exceptions in ValueError.
                # Re-raise the original MT5Error if it's in the cause chain.
                cause = exc.__context__
                while cause is not None:
                    if isinstance(cause, MT5Error):
                        raise cause
                    cause = cause.__context__
                raise
            content = asyncio.run(resource.read())
            return Quote.model_validate_json(content)
    raise KeyError(f"No resource template matched URI: {uri!r}")


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
    assert exc_info.value.detail.code in ("RESOURCE_NOT_FOUND", "SYMBOL_NOT_FOUND")
