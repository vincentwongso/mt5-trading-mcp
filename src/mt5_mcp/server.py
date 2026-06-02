"""MCP server factory.

`build_server()` returns a FastMCP instance with tools registered. The
actual connect-to-terminal happens on first tool call so `serve` can start
up even when MT5 is offline (tools just return TERMINAL_NOT_CONNECTED).

Subscribe hook wiring
---------------------
The low-level mcp.server.Server exposes `subscribe_resource()` and
`unsubscribe_resource()` decorators that register async handlers for the
MCP protocol's resources/subscribe and resources/unsubscribe requests.
FastMCP exposes the underlying server via `_mcp_server`.

We use this to wire protocol subscriptions into ctx.dispatcher so the
Poller activates and change notifications flow back to clients.  The
handler captures the current ServerSession and asyncio event loop; a
FastMCPSubscriber adapter bridges the sync Dispatcher.notify_updated()
call (from the Poller daemon thread) to the async
ServerSession.send_resource_updated() call.

FastMCP version: installed mcp package (1.x).  The `_mcp_server`
attribute is private but stable across 1.x minor versions; it is the
canonical way to reach subscribe hooks until FastMCP exposes them
publicly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import AnyUrl

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.adapter.symbols import SymbolPrep
from mt5_mcp.config import Config, ConfigWatcher, default_config_path, load_config
from mt5_mcp.policy import PolicyEngine
from mt5_mcp.streaming.dispatcher import Dispatcher, SubscriptionHandle
from mt5_mcp.streaming.poller import Poller


logger = logging.getLogger(__name__)


class FastMCPSubscriber:
    """Bridges the sync Dispatcher.notify_updated() to the async
    ServerSession.send_resource_updated() across the Poller daemon thread.

    Created once per (session, uri) pair inside the subscribe_resource handler.
    The handler runs in an asyncio task, so we capture the running loop and
    the live session object.  notify_updated() is called from the Poller
    thread and safely schedules the coroutine on the captured loop.
    """

    def __init__(self, session: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._session = session
        self._loop = loop

    def notify_updated(self, uri: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._session.send_resource_updated(AnyUrl(uri)),
            self._loop,
        )


@dataclass
class AppContext:
    """Hands-off wiring passed from the server to each tool/resource module."""

    client: MT5Client
    symbols: SymbolPrep
    config_watcher: ConfigWatcher | None
    policy: PolicyEngine
    dispatcher: Dispatcher
    poller: Poller

    @property
    def config(self) -> Config:
        if self.config_watcher is not None:
            return self.config_watcher.current
        return Config()


_ctx_lock = threading.Lock()
_ctx: AppContext | None = None

# Startup wait applied to the FIRST connect when programmatic-login credentials
# are present (the headless container boot path): the MT5 terminal can take a
# while to come up after `docker run`. ~30 × 2s ≈ a 60s boot window. The native
# attach path (no creds) gets no retries — a genuine failure should surface
# immediately rather than hang.
_BOOT_CONNECT_RETRIES = 30
_BOOT_CONNECT_RETRY_DELAY_S = 2.0


def build_context(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> AppContext:
    """Instantiate the client + symbol prep + config watcher + streaming."""
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            return _ctx
        # Config.
        watcher: ConfigWatcher | None = None
        path = config_path or default_config_path()
        if path.exists():
            watcher = ConfigWatcher(path)
            watcher.start()
            cfg = watcher.current
        else:
            cfg = load_config()  # defaults
        # Client. When no module is injected (production), resolve the backend
        # LAZILY per config — native import or the [mt5.bridge] RPyC proxy — so
        # the server constructs even on a host without MetaTrader5 installed.
        from mt5_mcp.adapter.mt5_client import resolve_mt5_module
        backend_label = (
            f"bridge → {cfg.mt5.bridge.host}:{cfg.mt5.bridge.port}"
            if cfg.mt5.bridge is not None
            else "native"
        )
        # Programmatic-login credentials: login/server come from the (already
        # env-overlaid) config; the password is env-only and read here so it
        # never enters a Config object that could be logged or serialized.
        # When a login is configured we're booting (likely in the container), so
        # give connect() a startup wait window for the terminal to come up.
        #
        # The password is only meaningful alongside a login — read it ONLY then,
        # so a half-filled .env (MT5_PASSWORD set, MT5_LOGIN missing) neither
        # retains an unusable secret on the client nor arms the boot retry window.
        booting_with_login = cfg.mt5.login is not None
        login_password = (
            (os.environ.get("MT5_PASSWORD") or None) if booting_with_login else None
        )
        client = MT5Client(
            terminal_path=cfg.mt5.terminal_path or None,
            login=cfg.mt5.login,
            password=login_password,
            server=cfg.mt5.server,
            connect_retries=(_BOOT_CONNECT_RETRIES if booting_with_login else 0),
            connect_retry_delay_s=_BOOT_CONNECT_RETRY_DELAY_S,
            mt5_module=mt5_module,
            mt5_factory=(None if mt5_module is not None else lambda: resolve_mt5_module(cfg)),
            backend_label=backend_label,
        )
        symbols = SymbolPrep(client)
        policy = PolicyEngine(
            config=cfg,
            idempotency_path=cfg.idempotency.path,
            audit_path=cfg.audit.path,
        )
        # Streaming (lazy-start: poller not started here).
        dispatcher = Dispatcher()
        poller = Poller(client=client, dispatcher=dispatcher, config=cfg.streaming)
        dispatcher.bind_poller(poller)
        _ctx = AppContext(
            client=client, symbols=symbols, config_watcher=watcher,
            policy=policy, dispatcher=dispatcher, poller=poller,
        )
        return _ctx


def get_context() -> AppContext:
    if _ctx is None:
        raise RuntimeError("AppContext not built; call build_context() first")
    return _ctx


def reset_context_for_tests() -> None:
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            try:
                _ctx.poller.stop()
            except Exception:
                pass
            if _ctx.config_watcher is not None:
                _ctx.config_watcher.stop()
            _ctx.policy.close()
        _ctx = None


def build_server(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> FastMCP:
    """Build a FastMCP server with all tools and resources registered."""
    build_context(config_path=config_path, mt5_module=mt5_module)
    mcp = FastMCP("mt5-mcp")
    from mt5_mcp.tools import register_tools
    from mt5_mcp.resources import register_resources

    register_tools(mcp)
    register_resources(mcp)
    _wire_subscribe_hooks(mcp)
    return mcp


def _wire_subscribe_hooks(mcp: FastMCP) -> None:
    """Register subscribe/unsubscribe handlers on the low-level MCP server.

    Uses mcp._mcp_server (a mcp.server.lowlevel.server.Server) which exposes
    subscribe_resource() and unsubscribe_resource() decorator factories.
    Both map a single async handler per message type — only one handler can
    be active at a time, so we handle all URIs in one place.

    Session-keyed handle map: dict[(uri_str, session_id)] -> SubscriptionHandle
    allows clean unsubscription when multiple clients subscribe to the same URI.
    """
    # Per-instance tracking: (uri_str, id(session)) -> SubscriptionHandle
    _active: dict[tuple[str, int], SubscriptionHandle] = {}
    _active_lock = threading.Lock()

    @mcp._mcp_server.subscribe_resource()
    async def _on_subscribe(uri: AnyUrl) -> None:
        uri_str = str(uri)
        ctx = get_context()
        try:
            loop = asyncio.get_running_loop()
            req_ctx = mcp._mcp_server.request_context
            session = req_ctx.session
        except Exception:
            logger.warning("subscribe_resource: could not capture session for %s", uri_str)
            return
        subscriber = FastMCPSubscriber(session=session, loop=loop)
        handle = ctx.dispatcher.subscribe(uri_str, subscriber)
        key = (uri_str, id(session))
        with _active_lock:
            old_handle = _active.get(key)
            _active[key] = handle
        if old_handle is not None:
            # Previous subscription for same (uri, session) — clean up the
            # orphan before it accumulates in the dispatcher.
            ctx.dispatcher.unsubscribe(old_handle)
        logger.debug("subscribe_resource: registered %s (session %s)", uri_str, id(session))

    @mcp._mcp_server.unsubscribe_resource()
    async def _on_unsubscribe(uri: AnyUrl) -> None:
        uri_str = str(uri)
        ctx = get_context()
        try:
            req_ctx = mcp._mcp_server.request_context
            session = req_ctx.session
        except Exception:
            logger.warning("unsubscribe_resource: could not find session for %s", uri_str)
            return
        key = (uri_str, id(session))
        with _active_lock:
            handle = _active.pop(key, None)
        if handle is not None:
            ctx.dispatcher.unsubscribe(handle)
            logger.debug("unsubscribe_resource: removed %s (session %s)", uri_str, id(session))
        else:
            logger.debug("unsubscribe_resource: no active sub for %s (session %s)", uri_str, id(session))
