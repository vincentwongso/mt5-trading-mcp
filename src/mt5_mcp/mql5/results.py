"""Turn parsed tester reports into the JSON document `mt5-mcp backtest` writes.

Balance only: the report has no floating equity over time, so drawdown
periods are closed-trade drawdowns. MT5's own maximum equity drawdown stays
in `metrics`.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from mt5_mcp.mql5.hostpath import host_paths
from mt5_mcp.mql5.report import Deal, PassRow, SingleResult

SCHEMA = 1
_MIN_DEPTH_PCT = 0.01


def balance_curve(deals: list[Deal]) -> list[dict]:
    return [{"time": d.time, "balance": d.balance} for d in deals]


def _days(a: str, b: str) -> float:
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400, 2)


def drawdowns(curve: list[dict]) -> list[dict]:
    """Balance drawdown periods, deepest first: peak, lowest point, recovery to the peak."""
    out: list[dict] = []
    peak = trough = None  # (balance, time)
    for p in curve:
        bal, t = p["balance"], p["time"]
        if peak is None:
            peak = (bal, t)
        elif trough is None:
            if bal > peak[0]:
                peak = (bal, t)
            elif bal < peak[0]:
                trough = (bal, t)
        elif bal >= peak[0]:
            out.append(_period(peak, trough, t))
            peak, trough = (bal, t), None
        elif bal < trough[0]:
            trough = (bal, t)
    if peak is not None and trough is not None:
        out.append(_period(peak, trough, None, last=curve[-1]["time"]))
    out = [d for d in out if d is not None]
    return sorted(out, key=lambda d: d["depth_pct"], reverse=True)


def _period(peak: tuple, trough: tuple, recovery: str | None, *, last: str | None = None) -> dict | None:
    depth = peak[0] - trough[0]
    pct = depth / peak[0] * 100 if peak[0] else 0.0
    if pct < _MIN_DEPTH_PCT:  # before rounding, so 0.005% is dropped rather than shown as 0.01
        return None
    return {
        "peak_time": peak[1],
        "trough_time": trough[1],
        "recovery_time": recovery,
        "depth": round(depth, 2),
        "depth_pct": round(pct, 2),
        "days": _days(peak[1], recovery or last),
    }


def costs(deals: list[Deal]) -> dict:
    return {"commission": round(sum(d.commission for d in deals), 2),
            "swap": round(sum(d.swap for d in deals), 2)}


def single_document(settings: dict, result: SingleResult, journal: dict | None, report: Path,
                    error: str | None = None) -> dict:
    curve = balance_curve(result.deals)
    return {
        "schema": SCHEMA,
        "kind": "single",
        "error": error,
        "settings": {**settings, "inputs": result.inputs},
        "metrics": result.metrics,
        "costs": costs(result.deals),
        "deals": [asdict(d) for d in result.deals],
        "balance": curve,
        "drawdowns": drawdowns(curve),
        "journal": journal,
        "report": host_paths(str(report)),
    }


def optimization_document(settings: dict, rows: list[PassRow], journal: dict | None, report: Path,
                          error: str | None = None) -> dict:
    passes = [{"rank": i, "pass": r.pass_no, "back": r.back, "forward": r.forward, "inputs": r.inputs}
              for i, r in enumerate(rows, 1)]
    return {"schema": SCHEMA, "kind": "optimization", "error": error, "settings": settings, "passes": passes,
            "journal": journal, "report": host_paths(str(report))}


def failure_document(kind: str, settings: dict, error: str, journal: dict | None, report: Path | None) -> dict:
    """A run with no usable report: what was asked, why it failed, and the journal."""
    return {"schema": SCHEMA, "kind": kind, "error": error, "settings": settings, "journal": journal,
            "report": host_paths(str(report)) if report else None}


def _finite(x):  # noqa: ANN001, ANN202
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x


def to_json(doc: dict) -> str:
    """Strict JSON: NaN and Infinity (e.g. a profit factor with no losses) become null."""
    return json.dumps(_finite(doc), indent=1, allow_nan=False)


def write_document(doc: dict, path: Path) -> None:
    path.write_text(to_json(doc) + "\n", encoding="utf-8")
