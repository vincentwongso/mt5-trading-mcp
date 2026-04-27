"""Tests for the positions://current resource read path."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server
from mt5_mcp.types import Position
from tests._resource_helpers import read_resource as _read_resource
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


def _parse_positions(payload: str) -> list[Position]:
    """Parse the JSON-array body returned by the positions resource.

    The handler returns ``list[Position]``, which FastMCP renders as a
    JSON array string. ``Position.model_validate_json`` only handles
    single objects, so we use Pydantic's TypeAdapter for the list.
    """
    from pydantic import TypeAdapter
    return TypeAdapter(list[Position]).validate_json(payload)


def test_positions_resource_returns_empty_when_none(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = ()
    payload = _read_resource(server, "positions://current")
    out = _parse_positions(payload)
    assert out == []


def test_positions_resource_returns_open_positions(server_and_mt5):
    server, fake = server_and_mt5
    fake._positions_get = (
        FakePosition(ticket=1, symbol="EURUSD", volume=0.10),
        FakePosition(ticket=2, symbol="GBPUSD", volume=0.20),
    )
    payload = _read_resource(server, "positions://current")
    out = _parse_positions(payload)
    assert {p.ticket for p in out} == {1, 2}
