import json
from pathlib import Path

from mt5_mcp.mql5.report import merge_passes, parse_opt_xml, parse_single_html
from mt5_mcp.mql5.results import (
    balance_curve,
    costs,
    drawdowns,
    optimization_document,
    single_document,
    write_document,
)

FIX = Path(__file__).parent / "fixtures" / "mql5" / "reports"


def _read(name):
    return (FIX / name).read_bytes()


def _curve(*pairs):
    return [{"time": f"2026-09-{d:02d}T00:00:00", "balance": b} for d, b in pairs]


def test_one_recovered_drawdown():
    dd = drawdowns(_curve((1, 100), (2, 110), (3, 99), (4, 105), (5, 111)))
    assert dd == [{"peak_time": "2026-09-02T00:00:00", "trough_time": "2026-09-03T00:00:00",
                   "recovery_time": "2026-09-05T00:00:00", "depth": 11.0, "depth_pct": 10.0, "days": 3.0}]


def test_unrecovered_and_equal_highs():
    dd = drawdowns(_curve((1, 100), (2, 100), (3, 90), (4, 100), (5, 95)))
    assert [d["recovery_time"] for d in dd] == ["2026-09-04T00:00:00", None]
    assert dd[0]["peak_time"] == "2026-09-01T00:00:00"  # equal high on day 2 does not restart
    assert dd[1]["days"] == 1.0  # unrecovered: peak to last point


def test_tiny_drawdowns_dropped():
    assert drawdowns(_curve((1, 10000), (2, 9999.5), (3, 10001))) == []


def test_deposit_only():
    r = parse_single_html(_read("single_failinit.htm"))
    assert drawdowns(balance_curve(r.deals)) == [] and costs(r.deals) == {"commission": 0.0, "swap": 0.0}


def test_single_document_from_fixture(tmp_path):
    r = parse_single_html(_read("single_deals.htm"))
    doc = single_document({"symbol": "EURUSD"}, r, None, Path("x.htm"))
    assert doc["schema"] == 1 and doc["kind"] == "single" and doc["journal"] is None
    assert doc["metrics"]["net_profit"] == 267.78 and len(doc["deals"]) == 97
    assert doc["deals"][1]["time"] == "2026-09-02T17:00:00" and doc["deals"][1]["sl"] is None
    assert doc["balance"][-1]["balance"] == 10267.78
    assert doc["costs"]["commission"] == round(sum(d.commission for d in r.deals), 2)
    assert doc["drawdowns"] and doc["drawdowns"][0]["depth_pct"] >= doc["drawdowns"][-1]["depth_pct"]
    assert doc["settings"]["inputs"] == {"MaximumRisk": "0.02", "DecreaseFactor": "3.0",
                                         "MovingPeriod": "12", "MovingShift": "6"}
    write_document(doc, tmp_path / "x.json")
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8")) == doc


def test_optimization_document_ranks_like_table():
    rows = merge_passes(parse_opt_xml(_read("opt_full_fwd.xml")), parse_opt_xml(_read("opt_full_fwd.forward.xml")))
    doc = optimization_document({"optimize": "full"}, rows, None, Path("x.xml"))
    assert doc["kind"] == "optimization" and doc["passes"][0]["pass"] == 68 and doc["passes"][0]["rank"] == 1
    assert doc["passes"][0]["forward"]["result"] == 10133.20 and doc["passes"][0]["inputs"]["MovingShift"] == "10"
    assert "deals" not in doc


def test_document_report_field_is_host_path(monkeypatch):
    monkeypatch.setenv("MT5_MCP_HOST_PATHS", "1")
    r = parse_single_html(_read("single_deals.htm"))
    assert single_document({}, r, None, Path(r"Z:\o\r.htm"))["report"] == "/o/r.htm"
    rows = merge_passes(parse_opt_xml(_read("opt_full_fwd.xml")), None)
    assert optimization_document({}, rows, None, Path(r"Z:\o\r.xml"))["report"] == "/o/r.xml"
