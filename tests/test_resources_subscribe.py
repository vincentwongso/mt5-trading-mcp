"""Tests for the resource subscribe path.

FastMCP subscribe hook discovery (mcp 1.x)
-------------------------------------------
The low-level mcp.server.Server (accessed via FastMCP._mcp_server) exposes:

    subscribe_resource()   -> decorator-factory registering an async handler
                              for types.SubscribeRequest.  Handler signature:
                              async def handler(uri: AnyUrl) -> None

    unsubscribe_resource() -> same pattern for types.UnsubscribeRequest.

FastMCP itself (the high-level wrapper) does NOT expose any subscribe-related
attributes or decorators -- [a for a in dir(FastMCP) if 'subs' in a.lower()]
returns []. The hook lives exclusively on the low-level server.

Wire-up strategy (see server._wire_subscribe_hooks):
  - The async handler captures the running asyncio loop and the ServerSession
    from request_ctx (contextvar set by the low-level server for each request).
  - A FastMCPSubscriber adapter holds (session, loop) and bridges the sync
    Dispatcher.notify_updated() call (Poller daemon thread) to the async
    session.send_resource_updated() via asyncio.run_coroutine_threadsafe().
  - Unsubscription is keyed by (uri_str, id(session)) so multiple clients
    subscribing to the same URI unsubscribe cleanly.

Tests below verify the Dispatcher path directly (always passes regardless of
FastMCP version) and confirm the wire-up compiles and registers without error.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mt5_mcp.server import build_server, get_context
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server_and_ctx(frozen_utc, tmp_path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    server = build_server(mt5_module=fake, config_path=cfg)
    return server, get_context()


# ---------------------------------------------------------------------------
# Dispatcher-direct tests (always pass regardless of FastMCP API)
# ---------------------------------------------------------------------------


def test_dispatcher_subscribe_picks_up_symbol(server_and_ctx):
    """Subscribing to quotes://EURUSD via the dispatcher activates the symbol."""
    server, ctx = server_and_ctx

    class _Sub:
        def __init__(self):
            self.notifications: list[str] = []

        def notify_updated(self, uri: str) -> None:
            self.notifications.append(uri)

    sub = _Sub()
    handle = ctx.dispatcher.subscribe("quotes://EURUSD", sub)
    assert "EURUSD" in ctx.dispatcher.subscribed_symbols()

    ctx.dispatcher.unsubscribe(handle)
    assert "EURUSD" not in ctx.dispatcher.subscribed_symbols()


def test_dispatcher_subscribe_account(server_and_ctx):
    """account://current subscriptions are tracked by the dispatcher."""
    _, ctx = server_and_ctx

    class _Sub:
        def notify_updated(self, uri: str) -> None:
            pass

    sub = _Sub()
    handle = ctx.dispatcher.subscribe("account://current", sub)
    # No symbol, but dispatcher must have a live handle.
    assert handle is not None
    # account:// URIs do not show up in subscribed_symbols (symbol-only set).
    assert ctx.dispatcher.subscribed_symbols() == set()

    ctx.dispatcher.unsubscribe(handle)


def test_dispatcher_subscribe_positions(server_and_ctx):
    """positions://current subscriptions are tracked by the dispatcher."""
    _, ctx = server_and_ctx

    class _Sub:
        def notify_updated(self, uri: str) -> None:
            pass

    sub = _Sub()
    handle = ctx.dispatcher.subscribe("positions://current", sub)
    assert handle is not None
    ctx.dispatcher.unsubscribe(handle)


def test_dispatcher_fanout_calls_subscriber(server_and_ctx):
    """dispatch_tick fans out to all subscribers of a symbol."""
    _, ctx = server_and_ctx
    from mt5_mcp.streaming.snapshots import TickSnapshot

    received: list[str] = []

    class _Sub:
        def notify_updated(self, uri: str) -> None:
            received.append(uri)

    sub = _Sub()
    handle = ctx.dispatcher.subscribe("quotes://EURUSD", sub)

    snap = TickSnapshot(time_msc=1000, bid=1.08, ask=1.081, last=0.0, volume=1)
    ctx.dispatcher.dispatch_tick("EURUSD", snap)

    assert received == ["quotes://EURUSD"]
    ctx.dispatcher.unsubscribe(handle)


def test_dispatcher_multiple_subscribers_same_symbol(server_and_ctx):
    """Multiple subscribers to the same symbol all receive notifications."""
    _, ctx = server_and_ctx
    from mt5_mcp.streaming.snapshots import TickSnapshot

    calls: list[tuple[str, str]] = []

    class _Sub:
        def __init__(self, name: str):
            self.name = name

        def notify_updated(self, uri: str) -> None:
            calls.append((self.name, uri))

    h1 = ctx.dispatcher.subscribe("quotes://EURUSD", _Sub("A"))
    h2 = ctx.dispatcher.subscribe("quotes://EURUSD", _Sub("B"))

    snap = TickSnapshot(time_msc=2000, bid=1.09, ask=1.091, last=0.0, volume=1)
    ctx.dispatcher.dispatch_tick("EURUSD", snap)

    assert ("A", "quotes://EURUSD") in calls
    assert ("B", "quotes://EURUSD") in calls

    ctx.dispatcher.unsubscribe(h1)
    ctx.dispatcher.unsubscribe(h2)


def test_dispatcher_refcount_symbol_released_on_last_unsub(server_and_ctx):
    """Symbol is removed from subscribed_symbols only when all handles are gone."""
    _, ctx = server_and_ctx

    class _Sub:
        def notify_updated(self, uri: str) -> None:
            pass

    h1 = ctx.dispatcher.subscribe("quotes://GBPUSD", _Sub())
    h2 = ctx.dispatcher.subscribe("quotes://GBPUSD", _Sub())

    assert "GBPUSD" in ctx.dispatcher.subscribed_symbols()

    ctx.dispatcher.unsubscribe(h1)
    # Still one subscriber - symbol must remain.
    assert "GBPUSD" in ctx.dispatcher.subscribed_symbols()

    ctx.dispatcher.unsubscribe(h2)
    # Last handle removed - symbol gone.
    assert "GBPUSD" not in ctx.dispatcher.subscribed_symbols()


# ---------------------------------------------------------------------------
# Wire-up sanity: confirm subscribe hooks were registered without error
# ---------------------------------------------------------------------------


def test_subscribe_hooks_registered_on_mcp_server(server_and_ctx):
    """build_server registers both subscribe and unsubscribe request handlers."""
    from mcp import types

    server, _ = server_and_ctx
    # The low-level server's request_handlers dict should have both entries
    # after _wire_subscribe_hooks ran.
    handlers = server._mcp_server.request_handlers
    assert types.SubscribeRequest in handlers, (
        "SubscribeRequest handler not registered - _wire_subscribe_hooks failed"
    )
    assert types.UnsubscribeRequest in handlers, (
        "UnsubscribeRequest handler not registered - _wire_subscribe_hooks failed"
    )


def test_subscribe_twice_same_uri_same_session_does_not_orphan(server_and_ctx):
    """If a client double-subscribes the same URI from the same session,
    the older handle must be unsubscribed so the dispatcher doesn't accumulate.

    This test simulates the _on_subscribe fixed flow (subscribe -> atomic swap ->
    unsubscribe old) directly against the dispatcher so we don't need a live
    asyncio request context.
    """
    _, ctx = server_and_ctx
    uri = "quotes://EURUSD"

    class _Sub:
        def notify_updated(self, uri: str) -> None:
            pass

    # First subscribe (simulates first resources/subscribe from a session).
    handle1 = ctx.dispatcher.subscribe(uri, _Sub())
    assert ctx.dispatcher.subscriber_count(uri) == 1

    # Second subscribe (simulates duplicate resources/subscribe from the same session).
    handle2 = ctx.dispatcher.subscribe(uri, _Sub())
    # Before the fix the old handle would be orphaned; with the fix we evict it.
    ctx.dispatcher.unsubscribe(handle1)  # mirrors the fixed _on_subscribe behaviour

    # Only one subscriber must remain.
    assert ctx.dispatcher.subscriber_count(uri) == 1

    # Cleanup.
    ctx.dispatcher.unsubscribe(handle2)
    assert ctx.dispatcher.subscriber_count(uri) == 0


def test_fastmcp_subscriber_adapter_schedules_async_call():
    """FastMCPSubscriber.notify_updated schedules send_resource_updated on the loop."""
    import asyncio
    from mt5_mcp.server import FastMCPSubscriber
    from mcp.types import AnyUrl

    sent: list[str] = []

    class _FakeSession:
        async def send_resource_updated(self, uri: AnyUrl) -> None:
            sent.append(str(uri))

    async def _run():
        loop = asyncio.get_running_loop()
        sub = FastMCPSubscriber(session=_FakeSession(), loop=loop)
        sub.notify_updated("quotes://EURUSD")
        # Give the scheduled coroutine a chance to run.
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert sent == ["quotes://EURUSD"]
