from pathlib import Path

from mt5_mcp.mql5.journal import LogLine, journal_block, parse_lines, read_new, snapshot_logs, summarize

J = Path(__file__).parent / "fixtures" / "mql5" / "journal"


def _lines(name):
    return parse_lines((J / name).read_bytes())


def test_failinit_not_started():
    j = summarize(_lines("failinit.log"), [], ea_stem="FailInit", optimization=False)
    assert j["started"] is False and j["crashed"] is False
    assert j["errors"] == ["Tester: tester stopped because OnInit returns non-zero code 1"]


def test_parameters_incorrect_also_not_started_in_single_run():
    j = summarize(_lines("optimization.log"), [], ea_stem="OptInit", optimization=False)
    assert j["started"] is False


def test_arrayerr_crashed():
    j = summarize(_lines("arrayerr.log"), [], ea_stem="ArrayErr", optimization=False)
    assert j["started"] is True and j["crashed"] is True
    assert j["errors"][0].startswith("ArrayErr (EURUSD,H1): ") and "array out of range" in j["errors"][0]


def test_notrade_ea_lines():
    j = summarize(_lines("notrade.log"), [], ea_stem="NoTrade", optimization=False)
    assert j["started"] is True and j["errors"] == [] and j["lines"] == 36
    assert j["ea_lines"] == ["2026.09.01 00:00:00   PROBE notrade init ok",
                             "2026.10.30 23:57:59   PROBE notrade deinit 1"]


def test_normal_run_started_no_errors():
    j = summarize(_lines("normal.log"), ["a.log"], ea_stem="MA", optimization=False)
    assert j["started"] is True and j["crashed"] is False and j["errors"] == [] and j["log_files"] == ["a.log"]


def test_optimization_never_judged():
    j = summarize(_lines("optimization.log"), [], ea_stem="OptInit", optimization=True)
    assert j["started"] is None and j["crashed"] is False and j["ea_lines"] == []
    assert len(j["errors"]) == 5  # odd P rejected by OnInit, informational only


def test_errors_capped_at_50():
    many = _lines("failinit.log") * 60
    assert len(summarize(many, [], ea_stem="FailInit", optimization=False)["errors"]) == 50


def test_read_new_returns_only_appended_bytes(tmp_path):
    log = tmp_path / "Tester" / "Agent-127.0.0.1-3000" / "logs" / "20261120.log"
    log.parent.mkdir(parents=True)
    old = (J / "normal.log").read_bytes()
    log.write_bytes(old)
    before = snapshot_logs(tmp_path)
    log.write_bytes(old + "CS\t0\t00:00:01.000\tTester\tnew line\r\n".encode("utf-16-le"))
    lines, files = read_new(tmp_path, before)
    assert [x.message for x in lines] == ["new line"]
    assert files == ["Tester\\Agent-127.0.0.1-3000\\logs\\20261120.log"]


def test_read_new_includes_file_created_during_run(tmp_path):
    logs = tmp_path / "Tester" / "Agent-127.0.0.1-3000" / "logs"
    logs.mkdir(parents=True)
    (logs / "20261120.log").write_bytes((J / "normal.log").read_bytes())
    before = snapshot_logs(tmp_path)
    (logs / "20261121.log").write_bytes((J / "notrade.log").read_bytes())
    lines, files = read_new(tmp_path, before)
    assert len(files) == 1 and files[0].endswith("20261121.log") and len(lines) == 36


def test_journal_block_failinit():
    j = summarize(_lines("failinit.log"), [], ea_stem="FailInit", optimization=False)
    block = journal_block(j)
    assert block.splitlines()[0] == "journal:"
    assert "  started: no" in block and "  error: Tester: tester stopped because OnInit returns non-zero code 1" in block
    assert "  ea: 2026.09.01 00:00:00   PROBE init fail now" in block


def test_journal_block_none_when_nothing_to_say():
    assert journal_block({"started": True, "crashed": False, "errors": [], "ea_lines": []}) is None


def test_no_start_line_is_unknown_not_failed():
    lines = [x for x in _lines("normal.log") if "testing of " not in x.message]
    j = summarize(lines, [], ea_stem="MA", optimization=False)
    assert j["started"] is None and j["crashed"] is False


def test_crash_error_found_behind_many_earlier_errors():
    noise = [LogLine(2, "ArrayErr (EURUSD,H1)", "2026.09.01 00:10:00   failed market buy 0.1 EURUSD [No money]")] * 60
    lines = _lines("arrayerr.log")
    j = summarize(noise + lines, [], ea_stem="ArrayErr", optimization=False)
    assert j["crashed"] is True and "array out of range" in j["crash_error"]
    assert len(j["errors"]) == 50 and any("critical error" in e for e in j["errors"])


def test_read_new_seeks_instead_of_reading_whole_files(tmp_path, monkeypatch):
    logs = tmp_path / "Tester" / "Agent-127.0.0.1-3000" / "logs"
    logs.mkdir(parents=True)
    old = logs / "20261119.log"
    old.write_bytes((J / "normal.log").read_bytes())
    cur = logs / "20261120.log"
    cur.write_bytes((J / "normal.log").read_bytes())
    before = snapshot_logs(tmp_path)
    with open(cur, "ab") as f:
        f.write("CS\t0\t00:00:01.000\tTester\tnew line\r\n".encode("utf-16-le"))

    def whole(self):
        raise AssertionError("read the whole file")

    monkeypatch.setattr(Path, "read_bytes", whole)
    lines, files = read_new(tmp_path, before)
    assert [x.message for x in lines] == ["new line"] and len(files) == 1
