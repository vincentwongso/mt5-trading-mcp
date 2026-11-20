"""Read Strategy Tester reports and print the summary an agent acts on.

Single runs write UTF-16 HTML (label/value table cells); optimisations write
an XML spreadsheet, plus `<report>.forward.xml` when forward testing is on.
Labels follow the terminal language and no setting to pin English was found
(probe 6), so unknown labels fail loudly rather than guess by position.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from mt5_mcp.mql5.tester import deposit_text


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
    if pct and "%" in t:
        t = t[:t.index("%")]  # real-tick runs print "100% real ticks"
    t = t.replace(" ", "").rstrip("%")
    try:
        return float(t)
    except ValueError:
        raise ReportError(f"not a number in report: {s!r}") from None


class _Rows(HTMLParser):
    """Table rows as lists of cell texts. Empty cells are kept: columns are positional."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "tr":
            self._end_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._buf is not None and self._row is not None:
            self._row.append("".join(self._buf).strip())  # inner spaces kept: they can be part of an input value
            self._buf = None
        elif tag in ("tr", "table"):
            self._end_row()

    def handle_data(self, data: str) -> None:
        if self._buf is not None:
            self._buf.append(data)

    def _end_row(self) -> None:
        if self._row is not None:
            self.rows.append(self._row)
        self._row = None

    def close(self) -> None:
        super().close()
        self._end_row()


@dataclass(frozen=True)
class Deal:
    time: str  # broker time, ISO 8601 without zone
    deal: int
    symbol: str
    type: str
    direction: str
    volume: float
    price: float | None
    order: int | None
    sl: float | None  # the order's initial stop; later modifications are not in the report
    tp: float | None
    commission: float
    swap: float
    profit: float
    balance: float
    comment: str


@dataclass(frozen=True)
class SingleResult:
    metrics: dict[str, float]
    inputs: dict[str, str]
    deals: list[Deal] = field(default_factory=list)
    header: dict[str, str | None] = field(default_factory=dict)


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


_DEAL_COLS = ("Time", "Deal", "Symbol", "Type", "Direction", "Volume", "Price", "Order",
              "Commission", "Swap", "Profit", "Balance", "Comment")
_ORDER_COLS = ("Order", "S / L", "T / P")


def _table(rows: list[list[str]], title: str, required: tuple[str, ...]) -> list[dict[str, str]]:
    """Data rows of the table under a title row, keyed by header name."""
    for i, row in enumerate(rows):
        if [c for c in row if c] == [title] and i + 1 < len(rows):
            header = rows[i + 1]
            missing = [c for c in required if c not in header]
            if missing:
                raise ReportError(f"{title} table has no {', '.join(missing)} column: "
                                  "the tester terminal's language is not English")
            out = []
            for r in rows[i + 2:]:
                if len(r) != len(header):
                    break
                out.append(dict(zip(header, r)))
            return out
    return []


def _iso(ts: str) -> str:
    return ts.replace(".", "-").replace(" ", "T")


def _opt(s: str) -> float | None:
    return parse_number(s) if s.strip() else None


def _deals(rows: list[list[str]]) -> list[Deal]:
    stops = {int(o["Order"]): (_opt(o["S / L"]), _opt(o["T / P"]))
             for o in _table(rows, "Orders", _ORDER_COLS) if o["Order"].strip()}
    deals = []
    for d in _table(rows, "Deals", _DEAL_COLS):
        order = int(d["Order"]) if d["Order"].strip() else None
        sl, tp = stops.get(order, (None, None)) if order is not None else (None, None)
        deals.append(Deal(
            time=_iso(d["Time"]), deal=int(d["Deal"]), symbol=d["Symbol"], type=d["Type"],
            direction=d["Direction"], volume=_opt(d["Volume"]) or 0.0, price=_opt(d["Price"]), order=order,
            sl=sl, tp=tp, commission=_opt(d["Commission"]) or 0.0, swap=_opt(d["Swap"]) or 0.0,
            profit=_opt(d["Profit"]) or 0.0, balance=parse_number(d["Balance"]), comment=d["Comment"],
        ))
    return deals


def _header(values: dict[str, str]) -> dict[str, str | None]:
    period = values.get("Period", "")
    m = re.match(r"(\S+) \((\d{4})\.(\d\d)\.(\d\d) - (\d{4})\.(\d\d)\.(\d\d)\)", period)
    deposit = values.get("Initial Deposit")
    return {
        "expert": values.get("Expert"),
        "symbol": values.get("Symbol"),
        "period": m[1] if m else (period or None),
        "from": f"{m[2]}-{m[3]}-{m[4]}" if m else None,
        "to": f"{m[5]}-{m[6]}-{m[7]}" if m else None,
        "currency": values.get("Currency"),
        "deposit": deposit_text(parse_number(deposit)) if deposit else None,
        "leverage": values.get("Leverage"),
    }


def parse_single_html(raw: bytes) -> SingleResult:
    p = _Rows()
    p.feed(_decode(raw))
    p.close()
    rows = p.rows
    values: dict[str, str] = {}
    for row in rows:
        for label, value in zip(row, row[1:]):
            if label.endswith(":"):
                values.setdefault(" ".join(label[:-1].split()), value)
    missing = [label for label, _ in _SINGLE.values() if label not in values]
    if missing:
        raise ReportError(
            f"report has no {', '.join(missing)}: the run did not finish, "
            "or the tester terminal's language is not English"
        )
    metrics = {k: parse_number(values[label], pct=pct) for k, (label, pct) in _SINGLE.items()}
    inputs: dict[str, str] = {}
    for i, row in enumerate(rows):
        if "Inputs:" in row:
            cells = [row[row.index("Inputs:") + 1]] if row.index("Inputs:") + 1 < len(row) else []
            for nxt in rows[i + 1:]:
                filled = [c for c in nxt if c]
                # Continuation rows have no label cell; a value may itself end in ":".
                if not nxt or nxt[0] or len(filled) != 1 or "=" not in filled[0]:
                    break
                cells.append(filled[0])
            for cell in cells:
                if "=" in cell:
                    name, value = cell.split("=", 1)
                    inputs[name] = value
            break
    return SingleResult(metrics, inputs, _deals(rows), _header(values))


@dataclass(frozen=True)
class OptTable:
    metrics: list[str]  # fixed columns, Pass..Trades
    inputs: list[str]  # one column per optimised input
    rows: list[dict[str, str]]  # metric columns only
    # Separate from rows: an input may be named like a metric (e.g. "Profit").
    input_rows: list[dict[str, str]]


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
    metrics, inputs = header[:split], header[split:]
    return OptTable(metrics, inputs, [dict(zip(metrics, r[:split])) for r in table[1:]],
                    [dict(zip(inputs, r[split:])) for r in table[1:]])


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
    for r, ins in zip(back.rows, back.input_rows):
        if forward and r["Pass"] not in fwd:
            continue  # MT5 may forward-test only some passes
        out.append(PassRow(
            int(r["Pass"]),
            _pick(r, "Result"),
            _pick(fwd[r["Pass"]], "Forward Result") if forward else None,
            dict(ins),
        ))
    out.sort(key=lambda p: (p.forward or p.back)["result"], reverse=True)
    return out


def _num(v: float) -> str:
    # Not :g, which rounds 10190.69 to 10190.7 and prints 1e+06.
    return f"{v:.6f}".rstrip("0").rstrip(".")


def format_single(r: SingleResult, report: Path) -> str:
    lines = [f"{k}: {_num(v)}" for k, v in r.metrics.items()]
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
            line += [_num(p.forward[k]) for k in ("result", "profit", "pf", "trades")]
        line += [_num(p.back[k]) for k in ("result", "profit", "pf", "dd_pct", "trades")]
        line += [p.inputs[n] for n in inputs]
        body.append(line)
    widths = [max(len(r[c]) for r in [head, *body]) for c in range(len(head))]
    text = ["  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in [head, *body]]
    return "\n".join([*text, f"report: {report}"])
