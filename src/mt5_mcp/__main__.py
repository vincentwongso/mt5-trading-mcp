"""Entry point: `python -m mt5_mcp`."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "serve":
        # Wired up in Task 9 (server bootstrap).
        raise SystemExit("serve not yet implemented")
    if argv[0] == "doctor":
        # Wired up in Task 15.
        raise SystemExit("doctor not yet implemented")
    if argv[0] == "export-symbols":
        # Wired up in Task 16.
        raise SystemExit("export-symbols not yet implemented")
    if argv[0] == "reload-config":
        # Wired up in Task 5.
        raise SystemExit("reload-config not yet implemented")
    print(f"Unknown command: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
