"""Server scaffolding only — real tool behaviour tested in tests/test_tools_*.py."""

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5


def test_build_server_registers_tools(tmp_path):
    reset_context_for_tests()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=FakeMT5(), config_path=cfg)
    # FastMCP exposes the tool manager; check registered tool count.
    tools = server._tool_manager.list_tools()
    names = {t.name for t in tools}
    expected = {
        "ping",
        "get_terminal_info",
        "get_account_info",
        "get_quote",
        "get_symbols",
        "get_market_hours",
        "get_rates",
        "calc_margin",
        "get_positions",
        "get_orders",
        "get_history",
        "place_order",
        "close_position",
        "modify_order",
        "cancel_order",
    }
    assert names == expected, f"missing or extra tools: {names ^ expected}"


def test_app_context_includes_policy_engine(tmp_path):
    """build_context() instantiates a PolicyEngine wired to per-OS paths."""
    from mt5_mcp.policy import PolicyEngine
    from mt5_mcp.server import build_context, reset_context_for_tests
    from tests.fakes import FakeMT5

    reset_context_for_tests()
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'[idempotency]\n'
        f'path = "{(tmp_path / "idem.db").as_posix()}"\n\n'
        f'[audit]\n'
        f'path = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    ctx = build_context(config_path=cfg_file, mt5_module=FakeMT5())
    try:
        assert isinstance(ctx.policy, PolicyEngine)
    finally:
        reset_context_for_tests()


def _sandbox_cfg(tmp_path) -> "object":
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    return cfg


def test_build_context_wires_credentials_from_env(monkeypatch, tmp_path):
    """The container path: MT5_LOGIN/PASSWORD/SERVER env → MT5Client. Password
    reaches the client but is never stored on the Config object."""
    from mt5_mcp.server import build_context, get_context, reset_context_for_tests

    monkeypatch.setenv("MT5_LOGIN", "7000592")
    monkeypatch.setenv("MT5_PASSWORD", "hunter2")
    monkeypatch.setenv("MT5_SERVER", "Fintrix-Live")
    reset_context_for_tests()
    build_context(mt5_module=FakeMT5(), config_path=_sandbox_cfg(tmp_path))
    try:
        client = get_context().client
        assert client.login == 7000592
        assert client.server == "Fintrix-Live"
        assert client._password == "hunter2"
    finally:
        reset_context_for_tests()


def test_build_context_no_credentials_leaves_client_attaching(monkeypatch, tmp_path):
    from mt5_mcp.server import build_context, get_context, reset_context_for_tests

    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.delenv("MT5_PASSWORD", raising=False)
    monkeypatch.delenv("MT5_SERVER", raising=False)
    reset_context_for_tests()
    build_context(mt5_module=FakeMT5(), config_path=_sandbox_cfg(tmp_path))
    try:
        client = get_context().client
        assert client.login is None
        assert client.server is None
        assert client._password is None
    finally:
        reset_context_for_tests()


def test_build_context_enables_startup_retries_with_credentials(monkeypatch, tmp_path):
    """Container boot (creds present) → connect() gets a startup wait window."""
    from mt5_mcp.server import build_context, get_context, reset_context_for_tests

    monkeypatch.setenv("MT5_LOGIN", "7000592")
    monkeypatch.setenv("MT5_PASSWORD", "pw")
    monkeypatch.setenv("MT5_SERVER", "S")
    reset_context_for_tests()
    build_context(mt5_module=FakeMT5(), config_path=_sandbox_cfg(tmp_path))
    try:
        assert get_context().client._connect_retries > 0
    finally:
        reset_context_for_tests()


def test_build_context_no_startup_retries_when_attaching(monkeypatch, tmp_path):
    """Native/attach path (no creds) → single connect attempt, fast-fail."""
    from mt5_mcp.server import build_context, get_context, reset_context_for_tests

    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.delenv("MT5_PASSWORD", raising=False)
    monkeypatch.delenv("MT5_SERVER", raising=False)
    reset_context_for_tests()
    build_context(mt5_module=FakeMT5(), config_path=_sandbox_cfg(tmp_path))
    try:
        assert get_context().client._connect_retries == 0
    finally:
        reset_context_for_tests()
