"""MQL5 compiler helpers: log parsing, kind detection, MetaEditor runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from mt5_mcp.mql5.compiler import (
    Diagnostic,
    detect_kind,
    format_diagnostic,
    install_target,
    parse_log,
    read_source,
)

FIX = Path(__file__).parent / "fixtures" / "mql5"
LOGS = FIX / "logs"


def test_parse_clean_log():
    log = parse_log((LOGS / "clean.log").read_bytes())
    assert (log.errors, log.warnings, log.diagnostics) == (0, 0, [])


def test_parse_error_log():
    log = parse_log((LOGS / "errors.log").read_bytes())
    assert log.errors == 1
    assert log.diagnostics == [Diagnostic(
        "C:\\mt5-compile-probe\\broken_ea.mq5", 4, 4, "error", 256,
        "undeclared identifier 'foo'",
    )]


def test_parse_warning_log_has_no_errors():
    log = parse_log((LOGS / "warnings.log").read_bytes())
    assert (log.errors, log.warnings) == (0, 1)
    assert [d.severity for d in log.diagnostics] == ["warning"]


def test_parse_include_error_points_at_mqh():
    log = parse_log((LOGS / "include_error.log").read_bytes())
    assert [d.path for d in log.diagnostics] == ["C:\\mt5-compile-probe\\inc\\broken.mqh"]


def test_parse_non_ascii_path_from_real_log():
    log = parse_log((LOGS / "non_ascii_path.log").read_bytes())
    assert log.errors == 0
    assert "C:\\mt5-compile-probe\\José\\clean_ea.mq5" in log.raw_text


def test_parse_space_and_non_ascii_path():
    raw = ("\ufeffC:\\Users\\José\\My EAs\\x.mq5(3,5) : error 256: 'foo' - undeclared identifier\r\n"
           "Result: 1 errors, 0 warnings\r\n").encode("utf-16-le")
    d = parse_log(raw).diagnostics[0]
    assert (d.path, d.line, d.col, d.code) == ("C:\\Users\\José\\My EAs\\x.mq5", 3, 5, 256)


def test_parse_diagnostic_without_position():
    raw = "\ufeffC:\\a.mq5 : error 123: cannot open file\r\nResult: 1 errors, 0 warnings\r\n".encode("utf-16-le")
    assert parse_log(raw).diagnostics == [Diagnostic("C:\\a.mq5", 0, 0, "error", 123, "cannot open file")]


def test_parse_utf8_log():
    raw = b"C:\\a.mq5(1,2) : warning 43: m\r\nResult: 0 errors, 1 warnings\r\n"
    log = parse_log(raw)
    assert (log.errors, log.warnings, log.diagnostics[0].col) == (0, 1, 2)


def test_parse_without_result_line():
    log = parse_log("garbage".encode("utf-16-le"))
    assert log.errors is None and log.warnings is None
    assert "garbage" in log.raw_text


def test_format_relative_under_cwd(tmp_path):
    d = Diagnostic(str(tmp_path / "src" / "a.mq5"), 42, 7, "error", 256, "'foo' - undeclared identifier")
    assert format_diagnostic(d, tmp_path) == f"{Path('src/a.mq5')}:42:7: error 256: 'foo' - undeclared identifier"


def test_format_absolute_outside_cwd(tmp_path):
    d = Diagnostic("/elsewhere/a.mq5", 1, 1, "warning", 43, "m")
    assert format_diagnostic(d, tmp_path) == "/elsewhere/a.mq5:1:1: warning 43: m"


@pytest.mark.parametrize("src,kind", [
    ("#property service\nvoid OnStart(){}", "Services"),
    ("#property library\nint f(){return 0;}", "Libraries"),
    ("int OnCalculate(const int a,const int b,const int c,const double &p[]){return a;}", "Indicators"),
    ("void OnStart(){}", "Scripts"),
    ("int OnInit(){return 0;} void OnTick(){}", "Experts"),
    ("// OnCalculate( mentioned\n/* void OnStart() */\nvoid OnTick(){}", "Experts"),
])
def test_detect_kind(src, kind):
    assert detect_kind(src) == kind


def test_detect_kind_real_indicator_fixture():
    assert detect_kind(read_source(FIX / "src" / "indicator.mq5")) == "Indicators"


@pytest.mark.parametrize("encoding,bom", [("utf-16-le", "\ufeff"), ("utf-16-be", "\ufeff"), ("utf-8", "\ufeff")])
def test_read_source_bom(tmp_path, encoding, bom):
    p = tmp_path / "i.mq5"
    p.write_bytes((bom + "int OnCalculate(){return 0;}").encode(encoding))
    assert detect_kind(read_source(p)) == "Indicators"


def test_install_target_uses_agent_subfolder(tmp_path):
    assert install_target(tmp_path, "Experts", "MyEA") == tmp_path / "MQL5" / "Experts" / "Agent" / "MyEA.ex5"


def test_install_target_libraries_at_root(tmp_path):
    assert install_target(tmp_path, "Libraries", "MyLib") == tmp_path / "MQL5" / "Libraries" / "MyLib.ex5"
