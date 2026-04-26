"""`python -m mt5_mcp export-symbols --output symbols.csv`."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from mt5_mcp.server import build_server, reset_context_for_tests


_COLUMNS = [
    "name",
    "description",
    "category",
    "contract_size",
    "tick_size",
    "volume_min",
    "volume_max",
    "volume_step",
    "currency_profit",
    "currency_margin",
    "filling_modes",
    "digits",
    "is_tradeable",
]


def run_export(*, output: Path, mt5_module: Any | None = None, config_path: Any | None = None) -> int:
    reset_context_for_tests()
    server = build_server(mt5_module=mt5_module, config_path=config_path)
    tm = server._tool_manager
    result = tm.get_tool("get_symbols").fn()
    if isinstance(result, dict) and "error" in result:
        print(f"error: {result['error']['code']}: {result['error']['message']}", file=sys.stderr)
        return 1
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        for sym in result:
            writer.writerow({
                "name": sym.name,
                "description": sym.description,
                "category": sym.category,
                "contract_size": str(sym.contract_size),
                "tick_size": str(sym.tick_size),
                "volume_min": str(sym.volume_min),
                "volume_max": str(sym.volume_max),
                "volume_step": str(sym.volume_step),
                "currency_profit": sym.currency_profit,
                "currency_margin": sym.currency_margin,
                "filling_modes": "|".join(sym.filling_modes),
                "digits": str(sym.digits),
                "is_tradeable": "true" if sym.is_tradeable else "false",
            })
    print(f"wrote {len(result)} symbols to {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mt5-mcp export-symbols")
    p.add_argument("--output", "-o", type=Path, default=Path("symbols.csv"))
    args = p.parse_args(argv)
    return run_export(output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
