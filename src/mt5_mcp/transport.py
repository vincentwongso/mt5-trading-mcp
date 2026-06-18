"""Transport selection: STDIO (default) and HTTP/SSE (opt-in).

HTTP mode binds loopback only and refuses to start otherwise. A configured
``transport.http.auth_token`` triggers a Starlette bearer-auth middleware with
constant-time token comparison; an empty token logs an unauthenticated-access
warning at startup.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
from typing import Any

from mt5_mcp.config import Config


logger = logging.getLogger(__name__)


class TransportConfigError(ValueError):
    """Raised when the transport configuration is invalid."""


class BearerAuthMiddleware:
    """ASGI middleware: 401 on missing/wrong Authorization: Bearer <token>."""

    def __init__(self, app, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        actual = headers.get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(actual, self._expected):
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            })
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return
        await self._app(scope, receive, send)


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def run(mcp: Any, *, transport: str, config: Config) -> None:
    """Boot the MCP server on the chosen transport.

    Raises ``TransportConfigError`` for invalid configurations BEFORE
    the server starts so the operator sees the failure on the same
    terminal that ran the command.
    """
    # Make the fail-open consent posture loud at startup. When the gate is off
    # (auto_approve_notional <= 0) every mutating call auto-executes with no
    # approval step - intended for a trusted/unattended agent, but worth saying
    # out loud. Mirrors the empty-auth_token warning below; fires on both
    # transports (placed before the stdio early-return).
    if config.policy.auto_approve_notional <= 0:
        logger.warning(
            "policy.auto_approve_notional is %s: the human-consent gate is OFF - "
            "every place_order / close_position / stop-widening modify "
            "auto-executes with NO approval step (full-open mode, for a trusted "
            "or unattended agent). Set policy.auto_approve_notional > 0 to require "
            "human approval on orders at or above that notional.",
            config.policy.auto_approve_notional,
        )
    # Eager connect (opt-in): establish the MT5 link now, on this (main) thread,
    # before entering the transport loop. Lazy connect otherwise runs on the
    # asyncio event-loop thread inside the first tool call, where the MetaTrader5
    # C-extension's first import + initialize() can take minutes and time out
    # stdio clients. Doing it here keeps the first tool call fast. Non-fatal:
    # if the terminal isn't up yet, log and fall back to the lazy path.
    if transport not in {"stdio", "http"}:
        raise TransportConfigError(f"unknown transport: {transport!r}")
    if transport == "http" and not _is_loopback(config.transport.http.host):
        host = config.transport.http.host
        raise TransportConfigError(
            f"transport.http.host must be a loopback address "
            f"(got {host!r}); set 127.0.0.1, ::1, or localhost"
        )
    if config.mt5.eager_connect:
        from mt5_mcp.server import get_context

        try:
            get_context().client.connect()
            logger.info("eager-connect: MT5 connection established at startup")
        except Exception as exc:  # noqa: BLE001 - any failure must not block startup
            logger.warning(
                "eager-connect: startup connect failed (%s); falling back to lazy "
                "connect on the first tool call",
                exc,
                exc_info=True,
            )
    if transport == "stdio":
        mcp.run()
        return
    # transport == "http" (validated, and loopback-enforced, by the guards above).
    _run_http(mcp, config)


def _run_http(mcp: Any, config: Config) -> None:
    """Serve the streamable-HTTP transport on loopback.

    Two paths, both serving FastMCP's streamable-HTTP app:

    * **No auth_token** - defer entirely to ``mcp.run(transport="streamable-http")``
      and log a loud unauthenticated-access warning.
    * **auth_token set** - wrap FastMCP's own ASGI app in ``BearerAuthMiddleware``
      and serve it through uvicorn exactly as ``FastMCP.run_streamable_http_async``
      does (same host/port, same log level). The mcp-package ``FastMCP`` exposes no
      ``add_middleware`` hook, and its built-in auth is OAuth-only, so a thin ASGI
      wrapper is the natural fit for a static shared-secret token.
    """
    http = config.transport.http
    # FastMCP reads host/port from settings, not from run() kwargs.
    mcp.settings.host = http.host
    mcp.settings.port = http.port
    # Extend (not replace) FastMCP's DNS-rebinding-protection allow list with
    # operator-configured hosts/origins. FastMCP defaults already cover localhost
    # variants; appending lets reverse proxies (Tailscale serve, Cloudflare Tunnel,
    # etc.) forward Host/Origin headers like `<machine>.<tailnet>.ts.net` without
    # tripping the 421 "Invalid Host header" guard.
    sec = mcp.settings.transport_security
    if http.trusted_hosts:
        sec.allowed_hosts = [*sec.allowed_hosts, *http.trusted_hosts]
    if http.trusted_origins:
        sec.allowed_origins = [*sec.allowed_origins, *http.trusted_origins]

    token = http.auth_token
    if not token:
        logger.warning(
            "transport.http.auth_token is empty: the loopback HTTP server "
            "accepts UNAUTHENTICATED requests - any local process (or a "
            "misconfigured port-forward) can place real trades. Set "
            "transport.http.auth_token whenever the HTTP transport is "
            "reachable beyond a single trusted user."
        )
        mcp.run(transport="streamable-http")
        return

    # Authenticated path. BearerAuthMiddleware passes non-HTTP scopes straight
    # through, so the lifespan event still reaches FastMCP's session manager.
    import uvicorn

    app = BearerAuthMiddleware(mcp.streamable_http_app(), token)
    uvicorn.run(
        app,
        host=http.host,
        port=http.port,
        log_level=mcp.settings.log_level.lower(),
    )
