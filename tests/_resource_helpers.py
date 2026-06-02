"""Shared helper for resource-handler tests.

Resolves a FastMCP resource URI (fixed or templated) and invokes the
registered handler, returning the read result (JSON string).

Verified against the installed mcp / FastMCP - look at
``server._resource_manager._templates`` if FastMCP changes shape.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mt5_mcp.errors import MT5Error


def read_resource(server: Any, uri: str) -> str:
    """Resolve a registered resource URI and return its read result.

    Returns the raw JSON-string body that ``resource.read()`` produces.
    Caller parses with ``Model.model_validate_json(content)`` themselves.

    Raises whatever the handler raises (e.g. ``MT5Error``) - the
    FastMCP-wrapping ``ValueError("Error creating resource from
    template: ...")`` is unwrapped via the cause chain so test code can
    use ``pytest.raises(MT5Error)`` directly.
    """
    rm = server._resource_manager
    # Templated URI path (e.g. quotes://EURUSD)
    if hasattr(rm, "_templates"):
        for tmpl in rm._templates.values():
            params = tmpl.matches(uri)
            if params:
                try:
                    resource = asyncio.run(tmpl.create_resource(uri, params))
                except ValueError as exc:
                    # FastMCP may use implicit (__context__) or explicit
                    # (__cause__) chaining - walk both to surface MT5Error.
                    cause = exc.__cause__ or exc.__context__
                    while cause is not None:
                        if isinstance(cause, MT5Error):
                            raise cause
                        cause = cause.__cause__ or cause.__context__
                    raise
                return asyncio.run(resource.read())
    # Fixed URI path (e.g. account://current, positions://current)
    res = asyncio.run(rm.get_resource(uri))
    return asyncio.run(res.read())
