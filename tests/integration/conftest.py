"""Fixtures and helpers for the Phase 5 live-broker integration suite.

This conftest overrides the unit-suite's autouse `_reset_app_context` so
the session-scope `live_server` can build the AppContext once and reuse
it across the integration session.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mt5_mcp.config import Config, load_config
from mt5_mcp.server import build_server, reset_context_for_tests


@pytest.fixture(autouse=True)
def _reset_app_context():
    """Override the unit-test autouse reset.

    The parent `tests/conftest.py` wipes the singleton AppContext between
    tests so unit tests can swap their FakeMT5 instances. Integration tests
    share one live MT5 connection across the session and MUST NOT have it
    torn down between tests. Tear-down happens in `live_server` teardown.
    """
    yield


@dataclass
class LiveServer:
    """Bundle yielded by the `live_server` fixture."""
    server: Any  # FastMCP — typed as Any to avoid an import for one annotation
    cfg: Config
    audit_path: Path
    idem_path: Path


def call_tool(live: LiveServer, name: str, **kwargs: Any) -> Any:
    """Invoke an MCP tool by name; return whatever the tool returns.

    Read tools return Pydantic model instances on success and a
    {"error": ...} dict on failure. Mutating tools always return a dict
    (containing either {ticket, success, ...} or {error: ...} or
    {request_id, summary, ...} for an approval preview). Test code is
    expected to check the actual shape returned by each tool — don't
    normalise here, the asymmetry is intentional in the production code.
    """
    return live.server._tool_manager.get_tool(name).fn(**kwargs)


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> LiveServer:
    """Build the FastMCP server against the real MetaTrader5 package.

    If MT5_LOGIN, MT5_PASSWORD, MT5_SERVER are all set in the environment,
    the fixture headlessly initialises the terminal first. Otherwise it
    falls back to attaching to a running, logged-in terminal.

    See `tests/integration/.env.example` for the env var template.

    Sandboxes idempotency DB + audit JSONL under tmp_path_factory so the
    user's real audit log is never touched. Cranks auto_approve_notional
    so 0.01-lot trades skip the approval gate (covered by Phase 2 units).
    """
    reset_context_for_tests()

    tmp = tmp_path_factory.mktemp("phase5")
    audit_path = tmp / "audit.jsonl"
    idem_path = tmp / "idem.db"
    cfg_path = tmp / "config.toml"
    cfg_path.write_text(
        '[policy]\n'
        'auto_approve_notional = "1000000"\n\n'
        f'[idempotency]\npath = "{idem_path.as_posix()}"\n\n'
        f'[audit]\npath = "{audit_path.as_posix()}"\n',
        encoding="utf-8",
    )

    # Headless launch when all three creds are set; else attach-fallback.
    login = os.environ.get("MT5_LOGIN")
    password = os.environ.get("MT5_PASSWORD")
    server = os.environ.get("MT5_SERVER")
    if login and password and server:
        try:
            import MetaTrader5 as mt5  # type: ignore[import]
        except ImportError:
            pytest.skip("MetaTrader5 package not importable — Phase 5 needs Windows + MT5")

        ok = mt5.initialize(login=int(login), password=password, server=server)
        if not ok:
            pytest.fail(
                "Phase 5 integration: mt5.initialize(login=<masked>, server=%r) "
                "returned False. Check MT5_LOGIN/PASSWORD/SERVER env vars or "
                "start the terminal manually and unset them." % server
            )

    fastmcp_server = build_server(mt5_module=None, config_path=cfg_path)
    cfg = load_config(cfg_path)

    yield LiveServer(
        server=fastmcp_server,
        cfg=cfg,
        audit_path=audit_path,
        idem_path=idem_path,
    )

    reset_context_for_tests()
