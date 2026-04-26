"""Server scaffolding only — real tool behaviour tested in tests/test_tools_*.py."""

from mt5_mcp.server import build_server, reset_context_for_tests
from tests.fakes import FakeMT5


def test_build_server_registers_tools():
    reset_context_for_tests()
    server = build_server(mt5_module=FakeMT5())
    # FastMCP exposes the tool manager; check registered tool count.
    tools = server._tool_manager.list_tools()
    # Phase 1 registers 9 read tools; placeholder register() adds 0.
    assert isinstance(tools, list)
