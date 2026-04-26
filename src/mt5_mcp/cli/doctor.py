"""`python -m mt5_mcp doctor` — green/red health report."""

from __future__ import annotations

import time
from typing import Any, Callable

from mt5_mcp.server import build_server, reset_context_for_tests


def _check(label: str, fn: Callable[[], Any]) -> bool:
    try:
        result = fn()
        if isinstance(result, dict) and "error" in result:
            print(f"[FAIL] {label}: {result['error']['code']} — {result['error']['message']}")
            return False
        print(f"[PASS] {label}")
        return True
    except Exception as exc:
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
        return False


def run_doctor(
    *,
    mt5_module: Any | None = None,
    probe_symbol: str = "EURUSD",
    config_path: Any | None = None,
    smoke_trade: bool = False,
) -> int:
    reset_context_for_tests()
    server = build_server(mt5_module=mt5_module, config_path=config_path)
    tm = server._tool_manager

    def call(name: str, **kwargs):
        return tm.get_tool(name).fn(**kwargs)

    results = []
    results.append(_check("ping", lambda: call("ping")))
    results.append(_check("get_terminal_info", lambda: call("get_terminal_info")))
    results.append(_check("get_account_info", lambda: call("get_account_info")))
    results.append(_check("get_symbols", lambda: call("get_symbols")))
    results.append(_check(f"get_quote({probe_symbol})", lambda: call("get_quote", symbol=probe_symbol)))
    results.append(_check(f"get_market_hours({probe_symbol})", lambda: call("get_market_hours", symbol=probe_symbol)))
    results.append(_check("get_positions", lambda: call("get_positions")))
    results.append(_check("get_orders", lambda: call("get_orders")))

    if smoke_trade:
        place = tm.get_tool("place_order").fn(
            symbol=probe_symbol, side="buy", type="market", volume="0.01",
            idempotency_key=f"doctor-{int(time.time())}",
        )
        if place.get("error") is not None:
            print(f"[FAIL] place_order: {place['error']['code']}")
            results.append(False)
        elif "request_id" in place:
            print(
                f"[SKIP] place_order returned approval preview "
                f"(auto_approve_notional too low for smoke?)"
            )
            # Treat skip as neither pass nor fail; don't flip the rc.
        else:
            ticket = place["ticket"]
            print(f"[PASS] place_order ticket={ticket}")

            close = tm.get_tool("close_position").fn(
                ticket=ticket,
                idempotency_key=f"doctor-close-{int(time.time())}",
            )
            if close.get("error") is not None or not close.get("success"):
                print(
                    f"[FAIL] close_position: "
                    f"{close.get('error', {}).get('code', '?')}"
                )
                results.append(False)
            else:
                print(f"[PASS] close_position ticket={ticket}")

    return 0 if all(results) else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="mt5-mcp doctor")
    parser.add_argument(
        "--smoke-trade", action="store_true",
        help="Round-trip a tiny place_order + close_position against the live "
             "terminal. WARNING: places a real (micro-lot) order on the broker.",
    )
    parser.add_argument(
        "--probe-symbol", default="EURUSD",
        help="Symbol used for read-tool probes (default: EURUSD).",
    )
    args = parser.parse_args(argv)
    return run_doctor(probe_symbol=args.probe_symbol, smoke_trade=args.smoke_trade)


if __name__ == "__main__":
    raise SystemExit(main())
