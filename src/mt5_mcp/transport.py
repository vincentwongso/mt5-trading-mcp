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
    if transport == "stdio":
        mcp.run()
        return
    if transport == "http":
        host = config.transport.http.host
        port = config.transport.http.port
        if not _is_loopback(host):
            raise TransportConfigError(
                f"transport.http.host must be a loopback address "
                f"(got {host!r}); set 127.0.0.1, ::1, or localhost"
            )
        # FastMCP 3.x reads host/port from mcp.settings, not from run() kwargs.
        # Mutate settings here so the correct address is used by uvicorn.
        mcp.settings.host = host
        mcp.settings.port = port
        # Extend FastMCP's DNS-rebinding-protection allow list with operator-
        # configured hosts. FastMCP defaults already cover localhost variants;
        # appending lets reverse proxies (Tailscale serve, Cloudflare Tunnel,
        # etc.) forward Host headers like `<machine>.<tailnet>.ts.net` without
        # tripping the 421 "Invalid Host header" guard.
        sec = mcp.settings.transport_security
        if config.transport.http.trusted_hosts:
            sec.allowed_hosts = list(sec.allowed_hosts) + list(config.transport.http.trusted_hosts)
        if config.transport.http.trusted_origins:
            sec.allowed_origins = list(sec.allowed_origins) + list(config.transport.http.trusted_origins)
        token = config.transport.http.auth_token
        if token:
            mcp.add_middleware(_make_bearer_middleware_factory(token))
        else:
            logger.warning(
                "transport.http.auth_token is empty: the loopback HTTP server "
                "accepts UNAUTHENTICATED requests - any local process (or a "
                "misconfigured port-forward) can place real trades. Set "
                "transport.http.auth_token whenever the HTTP transport is "
                "reachable beyond a single trusted user."
            )
        mcp.run(transport="streamable-http")
        return
    raise TransportConfigError(f"unknown transport: {transport!r}")


def _make_bearer_middleware_factory(token: str):
    """Return a callable FastMCP/Starlette accepts as a middleware spec.

    FastMCP's add_middleware may accept either a class or an instance.
    We store the token on the returned object so tests can introspect it.
    """
    expected = f"Bearer {token}"

    class _Factory:
        def __init__(self) -> None:
            self._expected = expected

        def __call__(self, app):
            return BearerAuthMiddleware(app, token)

        def __repr__(self) -> str:
            return f"<BearerAuthMiddlewareFactory token=...{token[-3:]}>"

    return _Factory()
