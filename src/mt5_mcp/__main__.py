"""Entry point: `python -m mt5_mcp <command>`.

Commands:
  serve              Run the MCP server on stdio (default).
  doctor             Run read-tool health check.
  export-symbols     Dump broker symbols to CSV.
  reload-config      Touch the config file so a running server reloads.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] == "serve":
        from mt5_mcp.server import build_server
        server = build_server()
        server.run(transport="stdio")
        return 0

    cmd = argv[0]

    if cmd == "doctor":
        from mt5_mcp.cli.doctor import main as doctor_main
        return doctor_main()

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
