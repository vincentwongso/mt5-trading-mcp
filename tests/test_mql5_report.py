from pathlib import Path

import pytest

from mt5_mcp.mql5.report import (
    OptTable,
    ReportError,
    format_single,
    format_table,
    merge_passes,
    parse_number,
    parse_opt_xml,
    parse_single_html,
)

FIX = Path(__file__).parent / "fixtures" / "mql5" / "reports"


def _read(name):
    return (FIX / name).read_bytes()


@pytest.mark.parametrize(("text", "pct", "want"), [
    ("10 000.00", False, 10000.0),
    ("10\u00a0000.00", False, 10000.0),
    ("-120.53", False, -120.53),
    ("147.91 (1.46%)", True, 1.46),
    ("5 (21.74%)", True, 21.74),
    ("100%", True, 100.0),
    ("23", False, 23.0),
])
def test_parse_number_grouped_negative_pct(text, pct, want):
    assert parse_number(text, pct=pct) == want


def test_parse_number_garbage_raises():
    with pytest.raises(ReportError):
        parse_number("n/a")


def test_single_en_fixture():
    r = parse_single_html(_read("single_en.htm"))
    m = r.metrics
    assert m["net_profit"] == 109.31
    assert m["gross_profit"] == 229.84 and m["gross_loss"] == -120.53
    assert m["profit_factor"] == 1.91 and m["expected_payoff"] == 4.75
    assert m["recovery_factor"] == 0.74 and m["sharpe"] == 2.07
    assert m["max_drawdown_pct"] == 1.46 and m["trades"] == 23
    assert m["win_rate_pct"] == 21.74 and m["history_quality_pct"] == 100
    assert r.inputs == {"MaximumRisk": "0.02", "DecreaseFactor": "3.0", "MovingPeriod": "12", "MovingShift": "6"}


def test_single_non_numeric_inputs_and_zero_trades():
    r = parse_single_html(_read("single_types.htm"))
    assert r.inputs == {"UseFilter": "false", "TradeMode": "0", "Note": "abc def",
                        "Start": "1760000000", "Lots": "0.25", "Span": "7"}
    assert r.metrics["trades"] == 0


def test_single_truncated_report_raises_reporterror():
    raw = _read("single_en.htm")
    with pytest.raises(ReportError):
        parse_single_html(raw[: len(raw) // 8])


def test_single_unrecognised_labels_says_language():
    text = _read("single_en.htm").decode("utf-16").replace("Total Net Profit:", "Gesamtnettogewinn:")
    with pytest.raises(ReportError, match="English"):
        parse_single_html(text.encode("utf-16"))


def test_opt_full_fixture():
    t = parse_opt_xml(_read("opt_full.xml"))
    assert len(t.rows) == 78
    assert t.inputs == ["MovingPeriod", "MovingShift"]
    assert t.rows[0]["Pass"] == "0" and t.rows[0]["Result"] == "10190.69"


def test_opt_genetic_fixture_same_shape():
    t = parse_opt_xml(_read("opt_genetic_fwd.xml"))
    assert len(t.rows) == 168 and t.inputs == ["MovingPeriod", "MovingShift"]


def test_forward_file_parses_with_forward_columns():
    t = parse_opt_xml(_read("opt_full_fwd.forward.xml"))
    assert "Forward Result" in t.metrics and t.inputs == ["MovingPeriod", "MovingShift"]
    assert t.rows[0]["Pass"] == "68"


def test_merge_ranks_by_forward_result():
    back = parse_opt_xml(_read("opt_full_fwd.xml"))
    fwd = parse_opt_xml(_read("opt_full_fwd.forward.xml"))
    rows = merge_passes(back, fwd)
    assert [r.pass_no for r in rows[:2]] == [68, 19]
    assert rows[0].forward["result"] == 10133.20
    assert rows[0].inputs == {"MovingPeriod": "12", "MovingShift": "10"}
    results = [r.forward["result"] for r in rows]
    assert results == sorted(results, reverse=True)


def test_merge_without_forward_ranks_by_back_result():
    rows = merge_passes(parse_opt_xml(_read("opt_full.xml")), None)
    assert rows[0].pass_no == 0 and rows[0].forward is None
    assert rows[0].back["result"] == 10190.69 and rows[0].back["trades"] == 78


def _table(rows, extra_metrics=()):
    metrics = ["Pass", *extra_metrics, "Result", "Profit", "Expected Payoff", "Profit Factor",
               "Recovery Factor", "Sharpe Ratio", "Custom", "Equity DD %", "Trades"]
    return OptTable(metrics=metrics, inputs=["P"], rows=[{k: v for k, v in r.items() if k != "P"} for r in rows],
                    input_rows=[{"P": r["P"]} for r in rows])


def _row(p, result, **kw):
    r = {"Pass": str(p), "Result": str(result), "Profit": "1", "Expected Payoff": "1",
         "Profit Factor": "1", "Recovery Factor": "1", "Sharpe Ratio": "1", "Custom": "0",
         "Equity DD %": "1", "Trades": "3", "P": str(p)}
    r.update(kw)
    return r


def test_merge_drops_passes_without_forward_row():
    back = _table([_row(1, 100), _row(2, 200), _row(3, 300)])
    fwd = _table([_row(1, 0, **{"Forward Result": "50", "Back Result": "100"}),
                  _row(3, 0, **{"Forward Result": "40", "Back Result": "300"})],
                 extra_metrics=("Forward Result", "Back Result"))
    rows = merge_passes(back, fwd)
    assert [r.pass_no for r in rows] == [1, 3]


def test_format_single_key_order_and_report_line():
    out = format_single(parse_single_html(_read("single_en.htm")), Path("C:/t/reports/x.htm"))
    lines = out.splitlines()
    assert lines[0] == "net_profit: 109.31"
    assert "trades: 23" in lines and "max_drawdown_pct: 1.46" in lines
    assert lines[-1].startswith("report: ") and lines[-1].endswith("x.htm")


def test_format_table_top_n_and_forward_columns():
    rows = merge_passes(parse_opt_xml(_read("opt_full_fwd.xml")), parse_opt_xml(_read("opt_full_fwd.forward.xml")))
    out = format_table(rows, 5, Path("r.xml"))
    lines = out.splitlines()
    assert lines[0].split()[:6] == ["rank", "pass", "fwd_result", "fwd_profit", "fwd_pf", "fwd_trades"]
    assert lines[0].split()[-2:] == ["MovingPeriod", "MovingShift"]
    assert len(lines) == 1 + 5 + 1
    assert lines[1].split()[:3] == ["1", "68", "10133.2"]
    assert lines[-1] == "report: r.xml"


def test_format_table_without_forward_has_no_fwd_columns():
    out = format_table(merge_passes(parse_opt_xml(_read("opt_full.xml")), None), 3, Path("r.xml"))
    assert "fwd_result" not in out.splitlines()[0]


def test_parse_number_real_ticks_history_quality():
    assert parse_number("100% real ticks", pct=True) == 100.0
    assert parse_number("98.5% real ticks", pct=True) == 98.5


def test_format_keeps_cents_and_avoids_exponents():
    rows = merge_passes(parse_opt_xml(_read("opt_full.xml")), None)
    head, first = format_table(rows, 1, Path("r.xml")).splitlines()[:2]
    assert first.split()[2] == "10190.69"
    from mt5_mcp.mql5.report import SingleResult
    out = format_single(SingleResult({"net_profit": 1000190.5, "trades": 51.0}, {}), Path("r.htm"))
    assert "net_profit: 1000190.5" in out and "trades: 51" in out


def test_single_input_value_ending_in_colon_is_kept():
    raw = _read("single_types.htm").decode("utf-16").replace("Note=abc def", "Note=prefix:")
    r = parse_single_html(raw.encode("utf-16"))
    assert r.inputs["Note"] == "prefix:" and r.inputs["Span"] == "7"


def test_opt_input_named_like_a_metric_does_not_overwrite_it():
    raw = _read("opt_full.xml").replace(b">MovingPeriod<", b">Profit<")
    t = parse_opt_xml(raw)
    assert t.inputs == ["Profit", "MovingShift"]
    rows = merge_passes(t, None)
    plain = merge_passes(parse_opt_xml(_read("opt_full.xml")), None)
    assert rows[0].back == plain[0].back
    assert rows[0].inputs["Profit"] == plain[0].inputs["MovingPeriod"]


def test_single_input_keeps_repeated_spaces():
    raw = _read("single_types.htm").decode("utf-16").replace("Note=abc def", "Note=abc  def")
    assert parse_single_html(raw.encode("utf-16")).inputs["Note"] == "abc  def"
