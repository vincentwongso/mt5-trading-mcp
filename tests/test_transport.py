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
class _StubFastMCP:
    """Captures run() args for assertions."""
    last_args: dict | None = None
    middlewares: list = None  # populated below

    def __post_init__(self):
        self.middlewares = []

    def add_middleware(self, mw):
        self.middlewares.append(mw)

    def run(self, **kwargs):
        self.last_args = kwargs


def _cfg(host="127.0.0.1", port=8765, token=""):
    return Config(
        transport=TransportSection(
            http=TransportHTTPSection(host=host, port=port, auth_token=token),
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
    assert mcp.last_args["host"] == "127.0.0.1"
    assert mcp.last_args["port"] == 8765


def test_run_http_with_token_installs_bearer_middleware():
    from mt5_mcp.transport import BearerAuthMiddleware
    mcp = _StubFastMCP()
    run(mcp, transport="http", config=_cfg(token="s3cr3t"))
    assert len(mcp.middlewares) == 1
    # Middleware factory may take the token at construction time.
    # Whatever the factory wraps it as, ensure the value is reachable.
    mw_obj = mcp.middlewares[0]
    assert "s3cr3t" in repr(mw_obj) or getattr(mw_obj, "_expected", "").endswith("s3cr3t")


def test_run_http_non_loopback_raises_config_error():
    mcp = _StubFastMCP()
    with pytest.raises(Exception) as exc_info:
        run(mcp, transport="http", config=_cfg(host="0.0.0.0"))
    assert "loopback" in str(exc_info.value).lower()


def test_run_unknown_transport_raises():
    mcp = _StubFastMCP()
    with pytest.raises(Exception):
        run(mcp, transport="ftp", config=_cfg())
