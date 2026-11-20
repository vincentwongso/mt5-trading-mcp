"""Strategy Tester run settings: the launch ini and `.set` input files.

Pure functions; nothing here touches a terminal. Values verified on build
6230 (see the backtest design spec's probe findings).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PERIODS = ("M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
           "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1")
MODELS = {"ticks": 0, "ohlc": 1, "real": 4}
OPTIMIZE = {"full": 1, "genetic": 2}
CRITERIA = {"balance": 0, "pf": 1, "payoff": 2, "dd": 3, "recovery": 4, "sharpe": 5, "custom": 6, "complex": 7}
FORWARD = {"off": 0, "1/2": 1, "1/3": 2, "1/4": 3}  # a custom date is mode 4


@dataclass(frozen=True)
class RunSpec:
    expert: str  # relative to MQL5\Experts
    symbol: str
    period: str
    date_from: date
    date_to: date
    deposit: float
    currency: str
    leverage: int
    model: str
    optimize: str | None
    criterion: str
    forward: str  # FORWARD key or YYYY-MM-DD; ignored for single runs
    set_name: str | None  # file name under MQL5\Profiles\Tester
    report: str  # relative to the tester folder, no extension


def build_ini(spec: RunSpec, *, disable_live: bool = True) -> str:
    lines = [
        "[Tester]",
        f"Expert={spec.expert}",
        f"Symbol={spec.symbol}",
        f"Period={spec.period}",
        f"Model={MODELS[spec.model]}",
        f"FromDate={spec.date_from:%Y.%m.%d}",
        f"ToDate={spec.date_to:%Y.%m.%d}",
        f"Deposit={spec.deposit:g}",
        f"Currency={spec.currency}",
        f"Leverage={spec.leverage}",
    ]
    if spec.set_name:
        lines.append(f"ExpertParameters={spec.set_name}")
    if spec.optimize:
        lines += [f"Optimization={OPTIMIZE[spec.optimize]}", f"OptimizationCriterion={CRITERIA[spec.criterion]}"]
        if spec.forward in FORWARD:
            lines.append(f"ForwardMode={FORWARD[spec.forward]}")
        else:
            lines += ["ForwardMode=4", f"ForwardDate={date.fromisoformat(spec.forward):%Y.%m.%d}"]
    else:
        lines += ["Optimization=0", "ForwardMode=0"]
    lines += [f"Report={spec.report}", "ReplaceReport=1", "ShutdownTerminal=1"]
    if disable_live:
        # The tester copy is logged into the live account; the tester still runs with these (probe 3).
        lines += ["[Experts]", "AllowLiveTrading=0", "Enabled=0"]
    return "\n".join(lines) + "\n"


def write_ini(path: Path, text: str) -> None:
    path.write_bytes(b"\xff\xfe" + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le"))


def parse_forward(value: str) -> str:
    if value in FORWARD:
        return value
    try:
        date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected one of {', '.join(FORWARD)} or YYYY-MM-DD, got {value!r}") from None
    return value


@dataclass(frozen=True)
class SetFile:
    fixed: dict[str, str]
    optimized: dict[str, str]  # name -> value (first field)


def parse_set(raw: bytes) -> SetFile:
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    fixed: dict[str, str] = {}
    optimized: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        name, rest = line.split("=", 1)
        fields = rest.split("||")
        # value||start||step||stop||Y (verified: 12||6||2||30||Y ran 6..30 step 2)
        target = optimized if len(fields) == 5 and fields[4].strip().upper() == "Y" else fixed
        target[name.strip()] = fields[0].strip()
    return SetFile(fixed, optimized)


def _same(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        # Reports print .set text verbatim (probe 11): bool, enum number, string, epoch.
        return a.strip().casefold() == b.strip().casefold()


def check_inputs(set_file: SetFile, used: dict[str, str], *, optimized_names: list[str] | None) -> str | None:
    """Why the run did not use the .set as given, or None if it did.

    MT5 silently ignores unknown names (probe 9), which would otherwise give a
    fresh-looking result for inputs nobody asked for.
    """
    if optimized_names is not None and sorted(optimized_names) != sorted(set_file.optimized):
        return (f"optimised inputs in the report {sorted(optimized_names)} differ from the "
                f".set's ||Y inputs {sorted(set_file.optimized)}")
    expected = dict(set_file.fixed)
    if optimized_names is None:
        expected.update(set_file.optimized)
    known = set(used) | set(optimized_names or ())
    for name, value in expected.items():
        if name not in known:
            return f"input {name} from the .set is not an input of this EA (MT5 ignored it)"
        if name in used and not _same(value, used[name]):
            return f"input {name}: the .set says {value} but the run used {used[name]}"
    return None
