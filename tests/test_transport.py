from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from mt5_mcp.config import (
    Config, PolicySection, TransportHTTPSection, TransportSection,
)
from mt5_mcp.transport import BearerAuthMiddleware, _is_loopback, run


def test_is_loopback_accepts_localhost_and_127_loopback():
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("::1") is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("0.0.0.0") is False
    assert _is_loopback("192.168.1.5") is False
    assert _is_loopback("example.com") is False


@dataclass
class _StubTransportSecurity:
    """Mirrors FastMCP's TransportSecuritySettings shape (allowed_hosts/origins)."""
    # Defaults match FastMCP's real defaults so tests verify "append, don't replace".
    allowed_hosts: list = None
    allowed_origins: list = None

    def __post_init__(self):
        if self.allowed_hosts is None:
            self.allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        if self.allowed_origins is None:
            self.allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


@dataclass
class _StubSettings:
    """Mutable settings bag matching FastMCP's real settings object."""
    host: str = "127.0.0.1"
    port: int = 8000
    # FastMCP.run_streamable_http_async serves with log_level=settings.log_level.lower().
    log_level: str = "INFO"
    transport_security: _StubTransportSecurity = None  # populated below

    def __post_init__(self):
        if self.transport_security is None:
            self.transport_security = _StubTransportSecurity()


# Sentinel returned by the stub's streamable_http_app(): lets tests assert the
# authenticated path wraps FastMCP's *own* ASGI app, not something it built itself.
_STUB_HTTP_APP = object()


@dataclass
class _StubFastMCP:
    """Captures run() args for assertions.

    FastMCP 3.x reads host/port from mcp.settings, not from run() kwargs.
    The stub exposes a real `settings` attribute so transport.run() can
    write to it, and records the kwargs actually passed to run().

    Deliberately has NO add_middleware(): the mcp-package FastMCP lacks it
    (that absence is the bug we're fixing), so the stub must not provide a
    method the real class doesn't have, or it could hide a regression.
    """
    last_args: dict | None = None
    settings: _StubSettings = None  # populated below

    def __post_init__(self):
        self.settings = _StubSettings()

    def streamable_http_app(self):
        return _STUB_HTTP_APP

    def run(self, **kwargs):
        self.last_args = kwargs


def _cfg(host="127.0.0.1", port=8765, token="", trusted_hosts=None,
         trusted_origins=None, auto_approve="0"):
    cfg = Config(
        policy=PolicySection(auto_approve_notional=auto_approve),
        transport=TransportSection(
            http=TransportHTTPSection(
                host=host, port=port, auth_token=token,
                trusted_hosts=trusted_hosts or [],
                trusted_origins=trusted_origins or [],
            ),
        ),
    )
    # Transport tests are not about eager-connect; keep it off so run() does not
    # incidentally touch get_context(). The eager-connect tests opt in explicitly.
    cfg.mt5.eager_connect = False
    return cfg


def test_run_stdio_calls_run_without_transport_kwargs():
    mcp = _StubFastMCP()
    run(mcp, transport="stdio", config=_cfg())
    # FastMCP STDIO mode: either no args or transport="stdio".
    assert mcp.last_args == {} or mcp.last_args == {"transport": "stdio"}


def test_run_http_loopback_no_token_defers_to_fastmcp_run():
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(host="127.0.0.1", port=8765))
    # No token: hand off entirely to FastMCP's own streamable-http runner.
    assert mcp.last_args["transport"] == "streamable-http"
    # FastMCP 3.x: host/port are set on mcp.settings, not passed to run().
    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8765


def test_run_http_with_token_wraps_app_in_bearer_auth_and_serves(monkeypatch):
    """Authenticated path: build FastMCP's own ASGI app, wrap it in
    BearerAuthMiddleware, and serve it via uvicorn on the loopback address -
    never touching add_middleware (which the mcp-package FastMCP lacks)."""
    captured = {}

    def fake_uvicorn_run(app, **kwargs):
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(token="s3cr3t", host="127.0.0.1", port=8765))

    app = captured["app"]
    assert isinstance(app, BearerAuthMiddleware)
    # Wraps FastMCP's *own* streamable-http app, with the configured token.
    assert app._app is _STUB_HTTP_APP
    assert app._expected.endswith("s3cr3t")
    # Served on the configured loopback address with FastMCP's own log level.
    assert captured["kwargs"]["host"] == "127.0.0.1"
    assert captured["kwargs"]["port"] == 8765
    assert captured["kwargs"]["log_level"] == "info"
    # Did NOT fall back to mcp.run().
    assert mcp.last_args is None


def test_run_http_empty_token_logs_unauthenticated_warning(caplog):
    """An empty auth_token means the loopback HTTP server is unauthenticated -
    a real-money foot-gun the operator must be warned about at startup."""
    import logging
    mcp = _StubFastMCP()
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="http", config=_cfg(token=""))
    assert any("unauthenticated" in r.message.lower() for r in caplog.records)
    # No token: defers to FastMCP's own runner rather than wrapping/serving itself.
    assert mcp.last_args["transport"] == "streamable-http"


def test_run_http_with_token_emits_no_unauthenticated_warning(monkeypatch, caplog):
    import logging
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)
    mcp = _StubFastMCP()
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="http", config=_cfg(token="s3cr3t"))
    assert not any("unauthenticated" in r.message.lower() for r in caplog.records)


def test_run_warns_when_consent_gate_off(caplog):
    """Full-open default (auto_approve_notional=0) means mutating calls
    auto-execute with no approval step - the operator must be told at startup.
    Fires on stdio too (before the early return), not just HTTP."""
    import logging
    mcp = _StubFastMCP()
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="stdio", config=_cfg(auto_approve="0"))
    assert any("consent gate is off" in r.message.lower() for r in caplog.records)


def test_run_no_gate_warning_when_armed(caplog):
    """With the gate armed (auto_approve_notional > 0) the startup warning is
    silent - the operator opted into approvals."""
    import logging
    mcp = _StubFastMCP()
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="stdio", config=_cfg(auto_approve="1000"))
    assert not any("consent gate is off" in r.message.lower() for r in caplog.records)


def test_run_http_non_loopback_raises_config_error():
    mcp = _StubFastMCP()
    with pytest.raises(Exception) as exc_info:
        run(mcp, transport="http", config=_cfg(host="0.0.0.0"))
    assert "loopback" in str(exc_info.value).lower()


def test_run_unknown_transport_raises():
    mcp = _StubFastMCP()
    with pytest.raises(Exception):
        run(mcp, transport="ftp", config=_cfg())


def test_run_http_no_trusted_hosts_leaves_security_defaults_intact():
    """Empty trusted_hosts/trusted_origins -> FastMCP's localhost defaults are preserved as-is."""
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg())
    assert mcp.settings.transport_security.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    assert mcp.settings.transport_security.allowed_origins == [
        "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
    ]


def test_run_http_appends_trusted_hosts_to_default_allowlist():
    """Non-empty trusted_hosts is appended (not replaced) so localhost still works."""
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(
        trusted_hosts=["example.host.com", "another.host"],
    ))
    assert mcp.settings.transport_security.allowed_hosts == [
        "127.0.0.1:*", "localhost:*", "[::1]:*",
        "example.host.com", "another.host",
    ]


def test_run_http_appends_trusted_origins_to_default_allowlist():
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(
        trusted_origins=["https://example.host.com"],
    ))
    assert mcp.settings.transport_security.allowed_origins == [
        "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
        "https://example.host.com",
    ]


def test_run_http_trusted_hosts_independent_of_trusted_origins():
    """Setting trusted_hosts alone leaves origins untouched, and vice-versa."""
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(trusted_hosts=["one.host"]))
    # Hosts modified, origins still defaults.
    assert "one.host" in mcp.settings.transport_security.allowed_hosts
    assert mcp.settings.transport_security.allowed_origins == [
        "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
    ]


def test_run_eager_connect_calls_connect_before_serving(monkeypatch):
    """With mt5.eager_connect set, run() establishes the MT5 link on the calling
    (main) thread BEFORE handing off to mcp.run(). The lazy connect otherwise runs
    on the asyncio loop thread inside the first tool call, where it can stall for
    minutes and time out stdio clients."""
    order = []

    class _FakeClient:
        def connect(self):
            order.append("connect")

    class _FakeCtx:
        client = _FakeClient()

    monkeypatch.setattr("mt5_mcp.server.get_context", lambda: _FakeCtx())
    mcp = _StubFastMCP()
    real_run = mcp.run

    def _record_run(**kw):
        order.append("run")
        return real_run(**kw)

    mcp.run = _record_run
    cfg = _cfg()
    cfg.mt5.eager_connect = True
    run(mcp, transport="stdio", config=cfg)
    assert order == ["connect", "run"]


def test_run_eager_connect_off_skips_context(monkeypatch):
    """With eager_connect off, run() must not touch the connection at startup, so
    the server still starts when MT5 is offline (lazy path preserved)."""
    def _boom():
        raise AssertionError("get_context must not be called when eager_connect is off")

    monkeypatch.setattr("mt5_mcp.server.get_context", _boom)
    mcp = _StubFastMCP()
    run(mcp, transport="stdio", config=_cfg())  # _cfg() pins eager_connect False
    assert mcp.last_args is not None  # server still started


def test_run_eager_connect_failure_is_non_fatal(monkeypatch, caplog):
    """A failed startup connect (e.g. terminal not up yet) must NOT stop the
    server - it logs a warning and falls back to the lazy connect."""
    import logging

    class _FailClient:
        def connect(self):
            raise RuntimeError("terminal not running")

    class _FakeCtx:
        client = _FailClient()

    monkeypatch.setattr("mt5_mcp.server.get_context", lambda: _FakeCtx())
    mcp = _StubFastMCP()
    cfg = _cfg()
    cfg.mt5.eager_connect = True
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="stdio", config=cfg)  # must not raise
    assert mcp.last_args is not None
    assert any("eager-connect" in r.message.lower() for r in caplog.records)


# --- BearerAuthMiddleware: direct ASGI behavior -----------------------------
# No FastMCP needed; drive the middleware as a raw ASGI app.

def _drive_asgi(app, scope):
    """Run an ASGI app once against a static scope; return (sent_messages, inner_called)."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def _http_scope(authorization: bytes | None):
    headers = [(b"authorization", authorization)] if authorization is not None else []
    return {"type": "http", "headers": headers}


def _spy_inner():
    calls = []

    async def inner(scope, receive, send):
        calls.append(scope)

    return inner, calls


def test_bearer_mw_rejects_missing_authorization():
    inner, calls = _spy_inner()
    sent = _drive_asgi(BearerAuthMiddleware(inner, "tok"), _http_scope(None))
    assert sent[0]["status"] == 401
    assert calls == []  # inner app never reached


def test_bearer_mw_rejects_wrong_token():
    inner, calls = _spy_inner()
    sent = _drive_asgi(BearerAuthMiddleware(inner, "tok"), _http_scope(b"Bearer nope"))
    assert sent[0]["status"] == 401
    assert calls == []


def test_bearer_mw_passes_through_correct_token():
    inner, calls = _spy_inner()
    sent = _drive_asgi(BearerAuthMiddleware(inner, "tok"), _http_scope(b"Bearer tok"))
    assert len(calls) == 1  # inner app invoked
    assert sent == []  # middleware sent nothing itself


def test_bearer_mw_passes_through_non_http_scope():
    """Lifespan/websocket scopes must reach the inner app untouched, or FastMCP's
    session manager would never start."""
    inner, calls = _spy_inner()
    sent = _drive_asgi(BearerAuthMiddleware(inner, "tok"), {"type": "lifespan"})
    assert len(calls) == 1
    assert sent == []


# --- Regression: exercise the REAL mcp-package FastMCP ----------------------

def test_real_fastmcp_http_with_token_does_not_raise(monkeypatch):
    """The original bug: run() called mcp.add_middleware(), which the
    mcp-package FastMCP has no attribute for, crashing on startup whenever a
    token was set. The _StubFastMCP can't catch this (it can't define a method
    the real class lacks), so assert against the real class here. uvicorn.run
    is stubbed so nothing actually serves."""
    from mcp.server.fastmcp import FastMCP

    served = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: served.update(app=app))
    real = FastMCP("regression-test")
    run(real, transport="http", config=_cfg(token="s3cr3t"))  # must not raise
    assert isinstance(served["app"], BearerAuthMiddleware)
