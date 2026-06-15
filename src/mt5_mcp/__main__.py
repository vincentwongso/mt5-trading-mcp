"""Entry point: `python -m mt5_mcp <command>`.

Commands:
  serve [--transport stdio|http]   Run the MCP server (default: stdio).
  doctor                            Run read-tool health check.
  export-symbols                    Dump broker symbols to CSV.
  reload-config                     Touch the config file so a running server reloads.
"""

from __future__ import annotations

import argparse
import sys


def _run_serve(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="mt5-mcp serve")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="MCP transport to run on (default: stdio).",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config TOML (default: per-OS user config dir).",
    )
    parser.add_argument(
        "--eager-connect", action=argparse.BooleanOptionalAction, default=None,
        help="Connect to MT5 at startup (main thread) instead of lazily on the "
             "first tool call, so stdio clients (Claude Desktop / Claude Code) "
             "don't hit a slow first call; falls back to lazy connect if the "
             "terminal isn't up yet. On by default - use --no-eager-connect to "
             "defer to lazy connect. Overrides [mt5] eager_connect.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    from pathlib import Path
    from mt5_mcp.config import load_config
    from mt5_mcp.server import build_server
    from mt5_mcp.transport import TransportConfigError, run

    config_path = Path(args.config) if args.config else None
    server = build_server(config_path=config_path)
    cfg = load_config(config_path)
    if args.eager_connect is not None:
        cfg.mt5.eager_connect = args.eager_connect
    try:
        run(server, transport=args.transport, config=cfg)
    except TransportConfigError as exc:
        print(f"transport error: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] == "serve":
        return _run_serve(argv[1:] if argv else [])

    cmd = argv[0]

    if cmd == "doctor":
        from mt5_mcp.cli.doctor import main as doctor_main
        return doctor_main(argv[1:])

    if cmd == "export-symbols":
        from mt5_mcp.cli.export_symbols import main as export_main
        return export_main(argv[1:])

    if cmd == "reload-config":
        import os
        from mt5_mcp.config import default_config_path
        path = default_config_path()
        if not path.exists():
            print(f"no config file at {path}", file=sys.stderr)
            return 1
        os.utime(path, None)
        print(f"touched {path}; running server should reload")
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    print(main.__doc__ or "", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
