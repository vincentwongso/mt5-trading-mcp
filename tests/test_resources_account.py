"""Tests for the account://current resource read path."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mt5_mcp.server import build_server
from tests._resource_helpers import read_resource as _read_resource
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


def test_account_resource_returns_account_info(server_and_mt5):
    server, _ = server_and_mt5
    payload = _read_resource(server, "account://current")
    from mt5_mcp.types import AccountInfo
    info = AccountInfo.model_validate_json(payload)
    assert info.login == 42
    assert info.balance == Decimal("10000.0")


def test_account_resource_currency_and_equity(server_and_mt5):
    server, _ = server_and_mt5
    payload = _read_resource(server, "account://current")
    from mt5_mcp.types import AccountInfo
    info = AccountInfo.model_validate_json(payload)
    assert info.currency == "USD"
    assert info.equity == Decimal("10050.0")
    assert info.leverage == 100
