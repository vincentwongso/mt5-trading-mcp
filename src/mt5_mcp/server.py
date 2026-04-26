"""MCP server factory.

`build_server()` returns a FastMCP instance with tools registered. The
actual connect-to-terminal happens on first tool call so `serve` can start
up even when MT5 is offline (tools just return TERMINAL_NOT_CONNECTED).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.adapter.symbols import SymbolPrep
from mt5_mcp.config import Config, ConfigWatcher, default_config_path, load_config
from mt5_mcp.policy import PolicyEngine


logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Hands-off wiring passed from the server to each tool module."""

    client: MT5Client
    symbols: SymbolPrep
    config_watcher: ConfigWatcher | None
    policy: PolicyEngine

    @property
    def config(self) -> Config:
        if self.config_watcher is not None:
            return self.config_watcher.current
        return Config()


_ctx_lock = threading.Lock()
_ctx: AppContext | None = None


def build_context(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> AppContext:
    """Instantiate the client + symbol prep + config watcher."""
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
        # Client.
        client = MT5Client(
            terminal_path=cfg.mt5.terminal_path or None,
            mt5_module=mt5_module,
        )
        symbols = SymbolPrep(client)
        policy = PolicyEngine(
            config=cfg,
            idempotency_path=cfg.idempotency.path,
            audit_path=cfg.audit.path,
        )
        _ctx = AppContext(client=client, symbols=symbols,
                          config_watcher=watcher, policy=policy)
        return _ctx


def get_context() -> AppContext:
    if _ctx is None:
        raise RuntimeError("AppContext not built; call build_context() first")
    return _ctx


def reset_context_for_tests() -> None:
    global _ctx
    with _ctx_lock:
        if _ctx is not None:
            if _ctx.config_watcher is not None:
                _ctx.config_watcher.stop()
            _ctx.policy.close()
        _ctx = None


def build_server(
    *,
    config_path: Path | None = None,
    mt5_module=None,
) -> FastMCP:
    """Build a FastMCP server with all Phase 1 read tools registered."""
    build_context(config_path=config_path, mt5_module=mt5_module)
    mcp = FastMCP("mt5-mcp")
    from mt5_mcp.tools import register_tools

    register_tools(mcp)
    return mcp
