"""`python -m mt5_mcp doctor` — green/red health report."""

from __future__ import annotations

import time
from typing import Any, Callable

from mt5_mcp.server import build_server, reset_context_for_tests


# When the user doesn't pass --probe-symbol, doctor tries these names against
# the broker's catalogue in order and uses the first match. Crypto first so
# weekend smoke-tests still find a streaming market; FX/metals/JPY-pair as
# weekday fallbacks. Brokers that suffix names (EURUSD.r, BTCUSD#, etc.) miss
# all candidates and trigger the "first available symbol" fallback.
_DEFAULT_PROBE_CANDIDATES: tuple[str, ...] = (
    "BTCUSD", "ETHUSD", "EURUSD", "XAUUSD", "USDJPY", "GBPUSD",
)


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


def _resolve_probe_symbol(requested: str, available: list[str]) -> str | None:
    """Pick a probe symbol the broker actually exposes.

    `requested != "auto"` is treated as an explicit user override and returned
    unchanged — even if it's missing on the broker, so the user sees the
    SYMBOL_NOT_FOUND failure they asked for.

    For `"auto"`, try `_DEFAULT_PROBE_CANDIDATES` in order, then fall back to
    the broker's first symbol. Returns `None` only if the broker has none.
    """
    if requested != "auto":
        return requested
    available_set = set(available)
    for candidate in _DEFAULT_PROBE_CANDIDATES:
        if candidate in available_set:
            return candidate
    return available[0] if available else None


def _streaming_check(symbol: str) -> bool:
    """Subscribe to quotes://{symbol}, run the poller for ~1s, assert >=1 tick."""
    from mt5_mcp.server import get_context

    ctx = get_context()
    received: list[str] = []

    class _Recorder:
        def notify_updated(self, uri: str) -> None:
            received.append(uri)

    handle = ctx.dispatcher.subscribe(f"quotes://{symbol}", _Recorder())
    try:
        # Poll up to ten short cycles or until we see a tick.
        for _ in range(10):
            ctx.poller.poll_once()
            if received:
                break
            time.sleep(0.1)
    finally:
        ctx.dispatcher.unsubscribe(handle)

    if received:
        print(f"[PASS] streaming({symbol}) — {len(received)} tick(s) dispatched")
        return True
    print(f"[FAIL] streaming({symbol}) — no ticks observed in ~1s")
    return False


def run_doctor(
    *,
    mt5_module: Any | None = None,
    probe_symbol: str = "auto",
    config_path: Any | None = None,
    smoke_trade: bool = False,
    check_streaming: bool = True,
) -> int:
    reset_context_for_tests()
    server = build_server(mt5_module=mt5_module, config_path=config_path)
    tm = server._tool_manager
    from mt5_mcp.server import get_context
    print(f"[INFO] backend: {get_context().client.backend_label}")

    def call(name: str, **kwargs):
        return tm.get_tool(name).fn(**kwargs)

    results = []
    # ping returns a plain dict {"ok": bool, "latency_ms": int, "via": str|None}
    # NOT an error envelope, so _check would always treat it as [PASS].
    # Inspect `ok` directly instead.
    ping_result = call("ping")
    if ping_result.get("ok"):
        via = ping_result.get("via")
        ms = ping_result.get("latency_ms", 0)
        print(f"[PASS] ping ({via}, {ms}ms)")
        results.append(True)
    else:
        print(f"[FAIL] ping: terminal unreachable (ok=false)")
        results.append(False)
    results.append(_check("get_terminal_info", lambda: call("get_terminal_info")))
    results.append(_check("get_account_info", lambda: call("get_account_info")))

    # get_symbols: capture the result so we can auto-pick a probe symbol from
    # the broker's actual catalogue. Inlined instead of going through _check
    # to avoid calling the tool twice.
    symbols_result = call("get_symbols")
    if isinstance(symbols_result, dict) and "error" in symbols_result:
        print(
            f"[FAIL] get_symbols: {symbols_result['error']['code']} — "
            f"{symbols_result['error']['message']}"
        )
        results.append(False)
        available_names: list[str] = []
    else:
        print("[PASS] get_symbols")
        results.append(True)
        available_names = [s.name for s in symbols_result]

    probe = _resolve_probe_symbol(probe_symbol, available_names)
    if probe_symbol == "auto" and probe is not None:
        print(f"[INFO] Auto-selected probe symbol: {probe}")

    if probe is None:
        print("[SKIP] symbol-dependent probes — broker exposes no symbols")
    else:
        results.append(_check(f"get_quote({probe})", lambda: call("get_quote", symbol=probe)))
        results.append(_check(f"get_market_hours({probe})", lambda: call("get_market_hours", symbol=probe)))

    results.append(_check("get_positions", lambda: call("get_positions")))
    results.append(_check("get_orders", lambda: call("get_orders")))

    if check_streaming and probe is not None:
        results.append(_streaming_check(probe))

    if smoke_trade:
        if probe is None:
            print("[SKIP] smoke-trade — broker exposes no symbols")
        else:
            place = tm.get_tool("place_order").fn(
                symbol=probe, side="buy", type="market", volume="0.01",
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
        "--probe-symbol", default="auto",
        help="Symbol used for read-tool probes. Default 'auto' picks the first "
             "of BTCUSD, ETHUSD, EURUSD, XAUUSD, USDJPY, GBPUSD that the broker "
             "exposes; if none match, the broker's first symbol is used. Pass an "
             "explicit symbol (e.g. 'EURUSD.r') to override.",
    )
    parser.add_argument(
        "--no-streaming-check", action="store_true",
        help="Skip the [streaming] subscribe-and-poll check.",
    )
    args = parser.parse_args(argv)
    return run_doctor(
        probe_symbol=args.probe_symbol,
        smoke_trade=args.smoke_trade,
        check_streaming=not args.no_streaming_check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
