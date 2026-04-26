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
