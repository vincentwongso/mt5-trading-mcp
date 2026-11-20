"""MQL5 compiler helpers: log parsing, kind detection, MetaEditor runs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mt5_mcp.mql5.compiler import (
    CompileTimeout,
    Diagnostic,
    build_command_line,
    built_ex5,
    detect_kind,
    format_diagnostic,
    install_target,
    parse_log,
    read_source,
    run_metaeditor,
    run_supervised,
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
    ('void OnTick(){ Print("OnStart() called"); }', "Experts"),
    ("void CFoo::OnStart(){} void OnTick(){ obj.OnStart(); }", "Experts"),
    ('string s = "#property library"; void OnTick(){}', "Experts"),
    ('string u = "http://x"; int OnCalculate(const int a){return a;}', "Indicators"),
    ('string c = "/*"; int OnCalculate(const int a){return a;}', "Indicators"),
    ("class CWorker { public: void OnStart() {} }; void OnTick() {}", "Experts"),
    ("class CInd { int OnCalculate(const int a) { return a; } }; void OnTick() {}", "Experts"),
    ("class C { void f() {} };\nvoid OnStart() {}", "Scripts"),
    ("void/* event handler */OnStart() {}", "Scripts"),
    ("#property/* exported */library\nint f() { return 0; }", "Libraries"),
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


def test_command_line_quotes_paths_with_spaces(tmp_path):
    src = tmp_path / "My EAs" / "x.mq5"
    src.parent.mkdir()
    src.write_text("void OnTick(){}")
    me = Path("C:/Program Files/MT5/metaeditor64.exe")
    inc = Path("C:/data dir/MQL5")
    log = Path("C:/t/x.log")
    cmd = build_command_line(me, src, inc, log)
    assert cmd == f'"{me}" /compile:"{src}" /inc:"{inc}" /log:"{log}"'


def test_command_line_accepts_upper_case_suffix(tmp_path):
    src = tmp_path / "X.MQ5"
    src.write_text("")
    assert f'/compile:"{src}"' in build_command_line(Path("me.exe"), src, tmp_path, tmp_path / "l.log")


@pytest.mark.parametrize("name", ["x.mqh", "x.txt"])
def test_command_line_refuses_non_mq5(tmp_path, name):
    p = tmp_path / name
    p.write_text("")
    with pytest.raises(ValueError):
        build_command_line(Path("me.exe"), p, tmp_path, tmp_path / "l.log")


@pytest.mark.parametrize("target", ["dir", "missing.mq5"])
def test_command_line_refuses_directory_or_missing(tmp_path, target):
    p = tmp_path / target
    if target == "dir":
        p = tmp_path / "folder.mq5"
        p.mkdir()
    with pytest.raises(ValueError):
        build_command_line(Path("me.exe"), p, tmp_path, tmp_path / "l.log")


class FakeProc:
    def __init__(self, *, returncode=0, wait_raises=None):
        self.pid = 4242
        self.returncode = returncode
        self._wait_raises = wait_raises
        self.killed = False
        self.cmdline = None

    def wait(self, timeout=None):
        if self._wait_raises is not None and not self.killed:
            raise self._wait_raises
        return self.returncode

    def poll(self):
        return None if (self._wait_raises is not None and not self.killed) else self.returncode

    def kill(self):
        self.killed = True


def _popen(proc):
    def popen(cmdline, *a, **k):
        proc.cmdline = cmdline
        return proc
    return popen


def test_run_passes_command_line_verbatim():
    proc = FakeProc()
    run_metaeditor('"me.exe" /compile:"a b.mq5"', timeout_s=5, popen=_popen(proc))
    assert proc.cmdline == '"me.exe" /compile:"a b.mq5"'


def test_run_kills_on_timeout():
    proc = FakeProc(wait_raises=subprocess.TimeoutExpired("me", 0.01))
    with pytest.raises(CompileTimeout):
        run_metaeditor("cmd", timeout_s=0.01, popen=_popen(proc))
    assert proc.killed


def test_run_kills_on_keyboard_interrupt():
    proc = FakeProc(wait_raises=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        run_metaeditor("cmd", timeout_s=5, popen=_popen(proc))
    assert proc.killed


def test_run_supervised_label_in_timeout_message():
    proc = FakeProc(wait_raises=subprocess.TimeoutExpired("t", 0.01))
    with pytest.raises(CompileTimeout, match="terminal did not finish"):
        run_supervised("cmd", timeout_s=0.01, label="terminal", popen=_popen(proc))


def test_run_supervised_custom_kill_called_on_timeout():
    proc = FakeProc(wait_raises=subprocess.TimeoutExpired("t", 0.01))
    calls = []

    def kill(p):
        calls.append(p)
        p.killed = True

    with pytest.raises(CompileTimeout):
        run_supervised("cmd", timeout_s=0.01, label="terminal", kill=kill, popen=_popen(proc))
    assert calls == [proc]


def test_run_returns_exit_code_without_killing():
    proc = FakeProc(returncode=1)
    assert run_metaeditor("cmd", timeout_s=5, popen=_popen(proc)) == 1
    assert not proc.killed


def test_built_ex5_next_to_source(tmp_path):
    src = tmp_path / "a.mq5"
    src.with_suffix(".ex5").write_bytes(b"")
    assert built_ex5(src, tmp_path / "MQL5", since=0) == tmp_path / "a.ex5"


def _write(path, mtime):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    os.utime(path, (mtime, mtime))


def test_built_ex5_ignores_stale_outputs(tmp_path):
    mql5 = tmp_path / "MQL5"
    src = mql5 / "Shared Projects" / "p" / "a.mq5"
    _write(src.with_suffix(".ex5"), 1000)                                     # stale, adjacent
    _write(mql5 / "Experts" / "Shared Projects" / "p" / "a.ex5", 1000)       # stale, other kind
    fresh = mql5 / "Indicators" / "Shared Projects" / "p" / "a.ex5"
    _write(fresh, 5000)
    assert built_ex5(src, mql5, since=4000) == fresh


def test_built_ex5_all_stale_is_none(tmp_path):
    src = tmp_path / "a.mq5"
    _write(src.with_suffix(".ex5"), 1000)
    assert built_ex5(src, tmp_path / "MQL5", since=4000) is None


@pytest.mark.parametrize("kind", ["Experts", "Indicators"])
def test_built_ex5_shared_projects_lands_in_kind_folder(tmp_path, kind):
    mql5 = tmp_path / "MQL5"
    src = mql5 / "Shared Projects" / "p" / "sub" / "a.mq5"
    out = mql5 / kind / "Shared Projects" / "p" / "sub" / "a.ex5"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"")
    assert built_ex5(src, mql5, since=0) == out


def test_built_ex5_missing(tmp_path):
    assert built_ex5(tmp_path / "a.mq5", tmp_path / "MQL5", since=0) is None


def test_run_waits_in_short_slices():
    seen = []

    class Slow(FakeProc):
        def wait(self, timeout=None):
            seen.append(timeout)
            if len(seen) < 3:
                raise subprocess.TimeoutExpired("me", timeout)
            return 0

    assert run_metaeditor("cmd", timeout_s=60, popen=_popen(Slow())) == 0
    assert len(seen) == 3 and all(t is not None and t <= 0.25 for t in seen)


def test_run_kills_real_slow_child_on_timeout():
    import sys
    procs = []

    def popen(cmdline):
        procs.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]))
        return procs[0]

    with pytest.raises(CompileTimeout):
        run_metaeditor("cmd", timeout_s=0.5, popen=popen)
    assert procs[0].poll() is not None


def test_diagnostic_from_drive_root_keeps_full_path():
    # docker exec runs from / (Z:\ under Wine); a root-relative path loses its drive and its host meaning.
    root = Path(Path.cwd().anchor)
    full = str(root / "w" / "src" / "a.mq5")
    d = Diagnostic(path=full, line=1, col=2, severity="error", code=157, message="m")
    assert format_diagnostic(d, root) == f"{full}:1:2: error 157: m"


def test_relative_diagnostic_uses_slashes_for_host_paths(monkeypatch):
    # docker exec -w <host dir>: the path is relative to the caller's folder and must read as a host path.
    from pathlib import PureWindowsPath

    import mt5_mcp.mql5.compiler as compiler

    monkeypatch.setenv("MT5_MCP_HOST_PATHS", "1")
    monkeypatch.setattr(compiler, "Path", PureWindowsPath)  # as under Wine
    d = Diagnostic(path=r"Z:\w\src\a.mq5", line=1, col=2, severity="error", code=157, message="m")
    assert format_diagnostic(d, PureWindowsPath(r"Z:\w")) == "src/a.mq5:1:2: error 157: m"
