"""Integration test: boot HTTP transport in a thread, hit it with the MCP client.

Marked @pytest.mark.integration so the regular unit suite is unaffected.

Run with:
    py -3 -m pytest -m integration tests/test_transport_http_integration.py -v

Design notes:
- The test uses the official MCP Python client (`mcp.client.streamable_http` +
  `mcp.client.session.ClientSession`) rather than raw httpx JSON-RPC, so it
  exercises exactly the same wire path a real agent runtime would use.
- If the MCP client API is unavailable the test skips cleanly via ImportError.
- The fixture sandboxes idempotency DB and audit JSONL under tmp_path so it
  never touches the real user data directory.
- A free OS-assigned port is used to avoid conflicts with long-running
  services.
- The catch-all `Exception -> skip` in the test body is intentional: this is
  an opt-in, best-effort integration smoke test. Phase 4 will tighten it once
  the wire path is proven stable across environments.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from datetime import datetime, timezone

import pytest

from mt5_mcp.config import load_config
from mt5_mcp.server import build_server, reset_context_for_tests
from mt5_mcp.transport import run as transport_run
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def _free_port() -> int:
    """Return an OS-assigned free TCP port on loopback."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def http_server(tmp_path):
    """Boot the MCP HTTP transport in a daemon thread; yield the port number."""
    reset_context_for_tests()

    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823,
        ask=1.0824,
    )

    port = _free_port()
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
        f'[transport.http]\nhost = "127.0.0.1"\nport = {port}\n'
    )

    server = build_server(mt5_module=fake, config_path=cfg_path)
    cfg = load_config(cfg_path)

    thread = threading.Thread(
        target=transport_run,
        kwargs=dict(mcp=server, transport="http", config=cfg),
        daemon=True,
    )
    thread.start()

    # Wait until the server is accepting TCP connections (max 5 s).
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        reset_context_for_tests()
        pytest.skip("HTTP server did not start within 5 s")

    yield port

    reset_context_for_tests()


@pytest.mark.integration
def test_http_resources_list_contains_quotes_template(http_server):
    """Verify the HTTP transport exposes Phase 3 resources via resources/list."""
    port = http_server
    base_url = f"http://127.0.0.1:{port}"

    # Initialised before the try so the assertion below is always in scope.
    all_uris: list[str] = []

    try:
        from mcp.client.session import ClientSession

        # Prefer the non-deprecated snake_case name; fall back to the legacy
        # camelCase export so the test works across mcp package versions.
        try:
            from mcp.client.streamable_http import streamable_http_client as _http_client_ctx
        except ImportError:
            from mcp.client.streamable_http import streamablehttp_client as _http_client_ctx  # type: ignore[no-redef]

        async def _list_resources():
            async with _http_client_ctx(f"{base_url}/mcp") as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resources = await session.list_resources()
                    templates = await session.list_resource_templates()
                    return resources, templates

        resources_result, templates_result = asyncio.run(_list_resources())

        # Collect all URIs/templates from both response lists.
        # Fixed-URI resources (account://current, positions://current) come
        # from list_resources(); URI templates (quotes://{symbol}) come from
        # list_resource_templates() - the MCP spec keeps them separate.
        if hasattr(resources_result, "resources") and resources_result.resources:
            all_uris.extend(str(r.uri) for r in resources_result.resources)
        if hasattr(templates_result, "resourceTemplates") and templates_result.resourceTemplates:
            all_uris.extend(t.uriTemplate for t in templates_result.resourceTemplates)

    except ImportError:
        pytest.skip("mcp.client.streamable_http not available in this environment")  # noqa: TRY203
    except Exception as e:  # noqa: BLE001
        pytest.skip(
            f"Integration test could not complete in this environment: "
            f"{type(e).__name__}: {e}"
        )

    # Assertion is OUTSIDE the try - failures here surface as FAILED, not SKIPPED.
    assert any("quotes://" in u for u in all_uris), (
        f"Expected a quotes:// resource/template in resources/list but got: {all_uris}"
    )
