"""Entry point: `python -m mt5_mcp`."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "serve":
        from mt5_mcp.server import build_server
        mcp = build_server()
        mcp.run(transport="stdio")
        return 0
    if argv[0] == "doctor":
        from mt5_mcp.cli.doctor import main as doctor_main
        return doctor_main()
    if argv[0] == "export-symbols":
        from mt5_mcp.cli.export_symbols import main as export_main
        return export_main(argv[1:])
    if argv[0] == "reload-config":
        # Sending SIGUSR1 isn't portable to Windows; the watchdog-based
        # auto-reload is the primary mechanism. This command just rewrites
        # the file's mtime, which triggers the watcher in a running server.
        import os as _os
        from mt5_mcp.config import default_config_path
        path = default_config_path()
        if not path.exists():
            print(f"no config file at {path}", file=sys.stderr)
            return 1
        _os.utime(path, None)
        print(f"touched {path}; running server should reload")
        return 0
    print(f"Unknown command: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
