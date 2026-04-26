"""`python -m mt5_mcp doctor` — green/red health report."""

from __future__ import annotations

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
    return 0 if all(results) else 1


def main() -> int:
    return run_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
