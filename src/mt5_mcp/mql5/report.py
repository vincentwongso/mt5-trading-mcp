"""Read Strategy Tester reports and print the summary an agent acts on.

Single runs write UTF-16 HTML (label/value table cells); optimisations write
an XML spreadsheet, plus `<report>.forward.xml` when forward testing is on.
Labels follow the terminal language and no setting to pin English was found
(probe 6), so unknown labels fail loudly rather than guess by position.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


class ReportError(Exception):
    pass


# Output key -> (English report label, value is a percentage)
_SINGLE = {
    "net_profit": ("Total Net Profit", False),
    "profit_factor": ("Profit Factor", False),
    "max_drawdown_pct": ("Equity Drawdown Maximal", True),
    "trades": ("Total Trades", False),
    "win_rate_pct": ("Profit Trades (% of total)", True),
    "sharpe": ("Sharpe Ratio", False),
    "expected_payoff": ("Expected Payoff", False),
    "recovery_factor": ("Recovery Factor", False),
    "gross_profit": ("Gross Profit", False),
    "gross_loss": ("Gross Loss", False),
    "history_quality_pct": ("History Quality", True),
}
# PassRow key -> back column; forward rows use "Forward Result" for result.
_PASS = {"result": "Result", "profit": "Profit", "pf": "Profit Factor", "sharpe": "Sharpe Ratio",
         "dd_pct": "Equity DD %", "trades": "Trades"}
_NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}


def parse_number(s: str, *, pct: bool = False) -> float:
    t = s.replace(" ", " ").strip()
    if "(" in t and ")" in t:
        inner, outer = t[t.index("(") + 1:t.index(")")], t[:t.index("(")]
        t = inner if pct else outer
    t = t.replace(" ", "").rstrip("%")
    try:
        return float(t)
    except ValueError:
        raise ReportError(f"not a number in report: {s!r}") from None


class _Cells(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "td":
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._buf is not None:
            text = " ".join("".join(self._buf).split())
            if text:
                self.cells.append(text)
            self._buf = None

    def handle_data(self, data: str) -> None:
        if self._buf is not None:
            self._buf.append(data)


@dataclass(frozen=True)
class SingleResult:
    metrics: dict[str, float]
    inputs: dict[str, str]


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def parse_single_html(raw: bytes) -> SingleResult:
    p = _Cells()
    p.feed(_decode(raw))
    cells = p.cells
    values: dict[str, str] = {}
    for label, value in zip(cells, cells[1:]):
        if label.endswith(":"):
            values.setdefault(label[:-1], value)
    missing = [label for label, _ in _SINGLE.values() if label not in values]
    if missing:
        raise ReportError(
            f"report has no {', '.join(missing)}: the run did not finish, "
            "or the tester terminal's language is not English"
        )
    metrics = {k: parse_number(values[label], pct=pct) for k, (label, pct) in _SINGLE.items()}
    inputs: dict[str, str] = {}
    if "Inputs:" in cells:
        for cell in cells[cells.index("Inputs:") + 1:]:
            if cell.endswith(":") or "=" not in cell:
                break
            name, value = cell.split("=", 1)
            inputs[name] = value
    return SingleResult(metrics, inputs)


@dataclass(frozen=True)
class OptTable:
    metrics: list[str]  # fixed columns, Pass..Trades
    inputs: list[str]  # one column per optimised input
    rows: list[dict[str, str]]


def parse_opt_xml(raw: bytes) -> OptTable:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ReportError(f"optimisation report is not valid XML: {exc}") from None
    table = [[(c.findtext("ss:Data", "", _NS) or "").strip() for c in r.findall("ss:Cell", _NS)]
             for r in root.iterfind(".//ss:Row", _NS)]
    if not table or "Trades" not in table[0]:
        raise ReportError("optimisation report has no Trades column: unfinished run, or terminal language not English")
    header = table[0]
    split = header.index("Trades") + 1
    return OptTable(header[:split], header[split:], [dict(zip(header, r)) for r in table[1:]])


@dataclass(frozen=True)
class PassRow:
    pass_no: int
    back: dict[str, float]
    forward: dict[str, float] | None
    inputs: dict[str, str]


def _pick(row: dict[str, str], result_col: str) -> dict[str, float]:
    cols = {**_PASS, "result": result_col}
    return {k: parse_number(row[c]) for k, c in cols.items()}


def merge_passes(back: OptTable, forward: OptTable | None) -> list[PassRow]:
    fwd = {r["Pass"]: r for r in forward.rows} if forward else {}
    out = []
    for r in back.rows:
        if forward and r["Pass"] not in fwd:
            continue  # MT5 may forward-test only some passes
        out.append(PassRow(
            int(r["Pass"]),
            _pick(r, "Result"),
            _pick(fwd[r["Pass"]], "Forward Result") if forward else None,
            {name: r[name] for name in back.inputs},
        ))
    out.sort(key=lambda p: (p.forward or p.back)["result"], reverse=True)
    return out


def format_single(r: SingleResult, report: Path) -> str:
    lines = [f"{k}: {v:g}" for k, v in r.metrics.items()]
    return "\n".join([*lines, f"report: {report}"])


def format_table(rows: list[PassRow], top: int, report: Path) -> str:
    has_fwd = bool(rows) and rows[0].forward is not None
    inputs = list(rows[0].inputs) if rows else []
    head = ["rank", "pass"]
    if has_fwd:
        head += ["fwd_result", "fwd_profit", "fwd_pf", "fwd_trades"]
    head += ["result", "profit", "pf", "dd_pct", "trades", *inputs]
    body = []
    for i, p in enumerate(rows[:top], 1):
        line = [str(i), str(p.pass_no)]
        if p.forward is not None:
            line += [f"{p.forward[k]:g}" for k in ("result", "profit", "pf", "trades")]
        line += [f"{p.back[k]:g}" for k in ("result", "profit", "pf", "dd_pct", "trades")]
        line += [p.inputs[n] for n in inputs]
        body.append(line)
    widths = [max(len(r[c]) for r in [head, *body]) for c in range(len(head))]
    text = ["  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in [head, *body]]
    return "\n".join([*text, f"report: {report}"])
