from __future__ import annotations

from dataclasses import dataclass

import pytest

from mt5_mcp.config import Config, StreamingSection, TransportHTTPSection, TransportSection
from mt5_mcp.transport import _is_loopback, run


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
    transport_security: _StubTransportSecurity = None  # populated below

    def __post_init__(self):
        if self.transport_security is None:
            self.transport_security = _StubTransportSecurity()


@dataclass
class _StubFastMCP:
    """Captures run() args for assertions.

    FastMCP 3.x reads host/port from mcp.settings, not from run() kwargs.
    The stub exposes a real `settings` attribute so transport.run() can
    write to it, and records the kwargs actually passed to run().
    """
    last_args: dict | None = None
    middlewares: list = None  # populated below
    settings: _StubSettings = None  # populated below

    def __post_init__(self):
        self.middlewares = []
        self.settings = _StubSettings()

    def add_middleware(self, mw):
        self.middlewares.append(mw)

    def run(self, **kwargs):
        self.last_args = kwargs


def _cfg(host="127.0.0.1", port=8765, token="", trusted_hosts=None, trusted_origins=None):
    return Config(
        transport=TransportSection(
            http=TransportHTTPSection(
                host=host, port=port, auth_token=token,
                trusted_hosts=trusted_hosts or [],
                trusted_origins=trusted_origins or [],
            ),
        ),
    )


def test_run_stdio_calls_run_without_transport_kwargs():
    mcp = _StubFastMCP()
    run(mcp, transport="stdio", config=_cfg())
    # FastMCP STDIO mode: either no args or transport="stdio".
    assert mcp.last_args == {} or mcp.last_args == {"transport": "stdio"}


def test_run_http_loopback_no_token_does_not_install_middleware():
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(host="127.0.0.1", port=8765))
    assert mcp.middlewares == []
    assert mcp.last_args["transport"] == "streamable-http"
    # FastMCP 3.x: host/port are set on mcp.settings, not passed to run().
    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8765


def test_run_http_with_token_installs_bearer_middleware():
    from mt5_mcp.transport import BearerAuthMiddleware
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(token="s3cr3t"))
    assert len(mcp.middlewares) == 1
    # Middleware factory may take the token at construction time.
    # Whatever the factory wraps it as, ensure the value is reachable.
    mw_obj = mcp.middlewares[0]
    assert "s3cr3t" in repr(mw_obj) or getattr(mw_obj, "_expected", "").endswith("s3cr3t")


def test_run_http_empty_token_logs_unauthenticated_warning(caplog):
    """An empty auth_token means the loopback HTTP server is unauthenticated -
    a real-money foot-gun the operator must be warned about at startup."""
    import logging
    mcp = _StubFastMCP()
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="http", config=_cfg(token=""))
    assert any("unauthenticated" in r.message.lower() for r in caplog.records)
    assert mcp.middlewares == []


def test_run_http_with_token_emits_no_unauthenticated_warning(caplog):
    import logging
    mcp = _StubFastMCP()
    with caplog.at_level(logging.WARNING, logger="mt5_mcp.transport"):
        run(mcp, transport="http", config=_cfg(token="s3cr3t"))
    assert not any("unauthenticated" in r.message.lower() for r in caplog.records)


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
    """Empty trusted_hosts/trusted_origins → FastMCP's localhost defaults are preserved as-is."""
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
