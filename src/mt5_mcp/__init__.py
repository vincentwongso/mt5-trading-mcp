"""mt5-mcp - MCP server wrapping the MetaTrader 5 Python library."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("mt5-trading-mcp")
except PackageNotFoundError:  # source checkout without install - rare
    __version__ = "0.0.0+unknown"
