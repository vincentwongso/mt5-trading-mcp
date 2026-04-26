"""Tool tests for ping + get_terminal_info."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server
from tests.fakes import FakeMT5, FakeTerminalInfo


@pytest.fixture
def server_and_mt5(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
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
    assert info.server == "Broker-Demo"


def test_get_terminal_info_when_disconnected(server_and_mt5):
    server, fake = server_and_mt5
    fake._terminal_info = None
    fake._account_info = None
    out = _call(server, "get_terminal_info")
    # When disconnected we still return a structured response — the code
    # surfaces TERMINAL_NOT_CONNECTED as an error detail.
    assert out["error"]["code"] == "TERMINAL_NOT_CONNECTED"
    assert out["error"]["requires_human"] is True


def test_error_envelope_catches_inner_mt5_error(server_and_mt5):
    """error_envelope catches MT5Error raised by the wrapped function itself.

    This exercises the ``try/except MT5Error`` at _common.py:43-46 — the
    inner-function-raise path — not the ensure_connected branch.
    The server_and_mt5 fixture is used only to ensure get_context() is
    initialised; the synthetic ``boom`` function stands in for a real tool.
    """
    from mt5_mcp.errors import MT5Error, terminal_not_connected_error
    from mt5_mcp.tools._common import error_envelope

    @error_envelope
    def boom() -> str:
        raise MT5Error(terminal_not_connected_error())

    _server, _fake = server_and_mt5  # establishes context via build_server
    out = boom()
    assert out["error"]["code"] == "TERMINAL_NOT_CONNECTED"
    assert out["error"]["requires_human"] is True
    assert out["error"].get("details") is None


def test_error_envelope_wraps_unexpected_exception_as_internal_error(
    server_and_mt5, caplog
):
    """A non-MT5Error from the tool body becomes an INTERNAL_ERROR envelope.

    Without the broader catch, a bare exception leaks a Python traceback to
    the MCP client. This exercises the ``except Exception`` branch added in
    Phase 1 cleanup.
    """
    import logging

    from mt5_mcp.tools._common import error_envelope

    @error_envelope
    def explode() -> str:
        raise KeyError("missing-thing")

    _server, _fake = server_and_mt5
    with caplog.at_level(logging.ERROR, logger="mt5_mcp.tools._common"):
        out = explode()
    assert out["error"]["code"] == "INTERNAL_ERROR"
    assert out["error"]["retryable"] is False
    assert out["error"]["requires_human"] is True
    # Exception type is surfaced in details so an operator can triage from
    # the envelope alone, but the raw traceback stays server-side (logs).
    assert out["error"]["details"] == {"exception_type": "KeyError"}
    assert "missing-thing" in out["error"]["message"]
    # Server-side log should carry the traceback for ops triage.
    assert any("explode" in r.message for r in caplog.records)
