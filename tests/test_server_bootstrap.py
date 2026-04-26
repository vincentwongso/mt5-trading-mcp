"""Server scaffolding only — real tool behaviour tested in tests/test_tools_*.py."""

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5


def test_build_server_registers_tools():
    reset_context_for_tests()
    server = build_server(mt5_module=FakeMT5())
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
    }
    assert names == expected, f"missing or extra tools: {names ^ expected}"
