import os
# tester_lock is used via ws.: a bare import named test* would be collected by pytest.
from datetime import datetime, timedelta, timezone

import pytest

from mt5_mcp.mql5 import workspace as ws
from mt5_mcp.mql5.workspace import (
    LockHeld,
    WorkspaceError,
    build_matches,
    is_set_up,
    log_tail,
    mirror_dependencies,
    new_report_name,
    read_origin,
    setup_tester,
    stage_ea,
    stage_set,
    write_origin,
)


@pytest.fixture
def live(tmp_path):
    install = tmp_path / "install"
    for d in ("MQL5", "Profiles/Charts", "bases", "Config"):
        (install / d).mkdir(parents=True)
    (install / "terminal64.exe").write_bytes(b"exe")
    (install / "x.dll").write_bytes(b"dll")
    (install / "Profiles/Charts/chart01.chr").write_text("ea attached")
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    for f in ("accounts.dat", "common.ini", "servers.dat", "terminal.ini"):
        (data / "config" / f).write_bytes(f.encode())
    return install, data


def test_setup_copies_top_level_files_and_config_only(live, tmp_path):
    install, data = live
    tester = tmp_path / "tester"
    setup_tester(install, data, tester)
    assert (tester / "terminal64.exe").read_bytes() == b"exe"
    assert (tester / "x.dll").is_file()
    for f in ("accounts.dat", "common.ini", "servers.dat"):
        assert (tester / "Config" / f).is_file()
    assert not (tester / "Config" / "terminal.ini").exists()
    for d in ("MQL5", "Profiles", "bases"):
        assert not (tester / d).exists()


def test_setup_never_copies_denylisted_even_if_required(live, tmp_path, monkeypatch):
    install, data = live
    monkeypatch.setattr(ws, "REQUIRED_DIRS", ("Profiles",))
    setup_tester(install, data, tmp_path / "tester")
    assert not (tmp_path / "tester" / "Profiles").exists()


def test_setup_rerun_keeps_tester_mql5_and_reports(live, tmp_path):
    install, data = live
    tester = tmp_path / "tester"
    setup_tester(install, data, tester)
    (tester / "MQL5" / "Experts").mkdir(parents=True)
    (tester / "MQL5" / "Experts" / "a.ex5").write_bytes(b"a")
    (tester / "reports").mkdir()
    (tester / "reports" / "r.htm").write_text("r")
    (install / "terminal64.exe").write_bytes(b"exe2")
    setup_tester(install, data, tester)
    assert (tester / "terminal64.exe").read_bytes() == b"exe2"
    assert (tester / "MQL5" / "Experts" / "a.ex5").is_file()
    assert (tester / "reports" / "r.htm").is_file()


def test_setup_missing_accounts_dat_raises(live, tmp_path):
    install, data = live
    (data / "config" / "accounts.dat").unlink()
    with pytest.raises(WorkspaceError, match="accounts.dat"):
        setup_tester(install, data, tmp_path / "tester")


def test_origin_roundtrip_and_missing_raises(tmp_path):
    with pytest.raises(WorkspaceError):
        read_origin(tmp_path)
    write_origin(tmp_path, tmp_path / "inst", tmp_path / "data")
    assert read_origin(tmp_path) == (tmp_path / "inst", tmp_path / "data")
    (tmp_path / "origin.json").write_text("{not json")
    with pytest.raises(WorkspaceError):
        read_origin(tmp_path)


def test_is_set_up_needs_exe_accounts_and_origin(live, tmp_path):
    install, data = live
    tester = tmp_path / "tester"
    assert not is_set_up(tester)
    setup_tester(install, data, tester)
    assert not is_set_up(tester)
    write_origin(tester, install, data)
    assert is_set_up(tester)


def test_build_matches_after_setup_and_not_after_live_update(live, tmp_path):
    install, data = live
    tester = tmp_path / "tester"
    setup_tester(install, data, tester)
    assert build_matches(install, tester)
    exe = install / "terminal64.exe"
    st = exe.stat()
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert not build_matches(install, tester)


def test_stage_ea_returns_agent_relative_path(tmp_path):
    ex5 = tmp_path / "MyEA.ex5"
    ex5.write_bytes(b"ex5")
    tester = tmp_path / "tester"
    assert stage_ea(ex5, tester) == "Agent\\MyEA.ex5"
    assert (tester / "MQL5" / "Experts" / "Agent" / "MyEA.ex5").read_bytes() == b"ex5"


@pytest.mark.parametrize("name", ["MyEA.mq5", "missing.ex5"])
def test_stage_ea_rejects_mq5_and_missing(tmp_path, name):
    p = tmp_path / name
    if name.endswith(".mq5"):
        p.write_text("x")
    with pytest.raises(WorkspaceError):
        stage_ea(p, tmp_path / "tester")


def test_stage_set_reencodes_utf8_to_utf16le_bom(tmp_path):
    src = tmp_path / "in.set"
    src.write_bytes("Lots=0.1\r\nNote=café\r\n".encode("utf-8"))
    assert stage_set(src, tmp_path / "tester", "run1") == "run1.set"
    out = (tmp_path / "tester" / "MQL5" / "Profiles" / "Tester" / "run1.set").read_bytes()
    assert out.startswith(b"\xff\xfe")
    assert out.decode("utf-16") == "Lots=0.1\r\nNote=café\r\n"


def test_mirror_dependencies_copies_newer_ex5_only(tmp_path):
    live, tester = tmp_path / "live", tmp_path / "tester"
    (live / "Indicators" / "Agent").mkdir(parents=True)
    (live / "Libraries").mkdir(parents=True)
    (live / "Indicators" / "Agent" / "ind.ex5").write_bytes(b"i")
    (live / "Indicators" / "Agent" / "ind.mq5").write_text("src")
    (live / "Libraries" / "lib.ex5").write_bytes(b"l")
    assert mirror_dependencies(live, tester) == 2
    assert (tester / "Indicators" / "Agent" / "ind.ex5").is_file()
    assert not (tester / "Indicators" / "Agent" / "ind.mq5").exists()
    assert mirror_dependencies(live, tester) == 0


def test_mirror_dependencies_without_live_folders_is_zero(tmp_path):
    assert mirror_dependencies(tmp_path / "live", tmp_path / "tester") == 0


def test_report_names_unique_within_one_second():
    t = datetime(2026, 11, 20, 2, 15, 23, 1, tzinfo=timezone.utc)
    a, b = new_report_name("MyEA", t), new_report_name("MyEA", t + timedelta(microseconds=1))
    assert a != b
    assert a.startswith("reports\\20261120T021523") and a.endswith("Z-MyEA")


def test_lock_second_acquire_raises_lockheld(tmp_path):
    with ws.tester_lock(tmp_path):
        with pytest.raises(LockHeld, match="another backtest is running"):
            with ws.tester_lock(tmp_path):
                pass


def test_lock_released_after_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with ws.tester_lock(tmp_path):
            raise RuntimeError
    with ws.tester_lock(tmp_path):
        pass


def test_lock_creates_missing_tester_dir(tmp_path):
    with ws.tester_lock(tmp_path / "new" / "tester"):
        assert (tmp_path / "new" / "tester").is_dir()


def test_log_tail_reads_utf16_logs_and_handles_missing(tmp_path):
    assert log_tail(tmp_path) == ""
    (tmp_path / "logs").mkdir()
    lines = "\r\n".join(f"line {i}" for i in range(30))
    (tmp_path / "logs" / "20261120.log").write_bytes(lines.encode("utf-16"))
    out = log_tail(tmp_path, n=5)
    assert "== " in out and "line 29" in out and "line 24" not in out


@pytest.mark.parametrize("where", ["data", "data/sub", "install", "install/sub", "parent"])
def test_check_tester_path_refuses_live_folders(live, tmp_path, where):
    install, data = live
    tester = tmp_path if where == "parent" else tmp_path / where
    with pytest.raises(WorkspaceError):
        ws.check_tester_path(tester, install, data)


def test_check_tester_path_refuses_foreign_non_empty_folder(live, tmp_path):
    install, data = live
    other = tmp_path / "other"
    other.mkdir()
    (other / "doc.txt").write_text("x")
    with pytest.raises(WorkspaceError, match="not empty"):
        ws.check_tester_path(other, install, data)
    ws.check_tester_path(tmp_path / "fresh", install, data)
    write_origin(other, install, data)
    ws.check_tester_path(other, install, data)  # an existing tester is fine


def test_check_tester_path_allows_rerun_after_failed_setup(live, tmp_path):
    install, data = live
    (data / "config" / "accounts.dat").unlink()
    tester = tmp_path / "tester"
    with ws.tester_lock(tester):
        with pytest.raises(WorkspaceError):
            setup_tester(install, data, tester)
    ws.check_tester_path(tester, install, data)  # our own half-made folder


def test_mirror_dependencies_recopies_when_live_build_is_older(tmp_path):
    live, tester = tmp_path / "live", tmp_path / "tester"
    src = live / "Indicators" / "ind.ex5"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"new")
    mirror_dependencies(live, tester)
    src.write_bytes(b"old")
    st = src.stat()
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns - 10**10))  # a restored, older build
    assert mirror_dependencies(live, tester) == 1
    assert (tester / "Indicators" / "ind.ex5").read_bytes() == b"old"


def test_check_tester_path_refuses_link_into_live_data(live, tmp_path):
    install, data = live
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(data, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted here")
    with pytest.raises(WorkspaceError):
        ws.check_tester_path(alias / "tester", install, data)


def test_failed_setup_rerun_clears_origin(live, tmp_path):
    install, data = live
    tester = tmp_path / "tester"
    setup_tester(install, data, tester)
    write_origin(tester, install, data)
    (data / "config" / "common.ini").unlink()
    with pytest.raises(WorkspaceError):
        setup_tester(install, data, tester)
    assert not is_set_up(tester)


def test_mirror_dependencies_removes_copies_whose_source_is_gone(tmp_path):
    live, tester = tmp_path / "live", tmp_path / "tester"
    (live / "Indicators" / "Agent").mkdir(parents=True)
    (live / "Libraries").mkdir(parents=True)
    (live / "Indicators" / "Agent" / "a.ex5").write_bytes(b"a")
    (live / "Indicators" / "Agent" / "b.ex5").write_bytes(b"b")
    (live / "Libraries" / "lib.ex5").write_bytes(b"l")
    mirror_dependencies(live, tester)
    (live / "Indicators" / "Agent" / "b.ex5").unlink()
    (live / "Libraries" / "lib.ex5").unlink()
    (live / "Libraries").rmdir()
    mirror_dependencies(live, tester)
    assert (tester / "Indicators" / "Agent" / "a.ex5").is_file()
    assert not (tester / "Indicators" / "Agent" / "b.ex5").exists()
    assert not (tester / "Libraries" / "lib.ex5").exists()


def test_mirror_dependencies_includes_experts(tmp_path):
    live, tester = tmp_path / "live", tmp_path / "tester"
    (live / "Experts" / "Project").mkdir(parents=True)
    (live / "Experts" / "Project" / "X.ex5").write_bytes(b"x")
    mirror_dependencies(live, tester)
    assert (tester / "Experts" / "Project" / "X.ex5").is_file()


def test_lock_wait_acquires_after_release(tmp_path):
    import threading
    import time

    held, released, waits = threading.Event(), threading.Event(), []

    def hold():
        with ws.tester_lock(tmp_path):
            held.set()
            time.sleep(1.5)
            released.set()

    t = threading.Thread(target=hold)
    t.start()
    held.wait()
    with ws.tester_lock(tmp_path, wait=True, on_wait=lambda: waits.append(1)):
        assert released.is_set()
    t.join()
    assert waits == [1]


def test_lock_wait_gives_up_on_a_non_contention_error(tmp_path, monkeypatch):
    import errno

    def broken(f):
        raise OSError(errno.EBADF, "Bad file descriptor")

    def no_retry(_):
        raise AssertionError("retried a lock error that is not contention")

    monkeypatch.setattr(ws, "_try_lock", broken)
    monkeypatch.setattr(ws.time, "sleep", no_retry)
    with pytest.raises(OSError, match="Bad file descriptor"):
        with ws.tester_lock(tmp_path, wait=True):
            pass


def test_lock_wait_retries_wines_errno_zero(tmp_path, monkeypatch):
    # Under Wine, msvcrt.locking reports contention as errno 0 (probed 2026-11-21).
    calls = []

    def busy_once(f):
        calls.append(1)
        if len(calls) == 1:
            raise OSError(0, "Error")

    monkeypatch.setattr(ws, "_try_lock", busy_once)
    monkeypatch.setattr(ws.time, "sleep", lambda _: None)
    with ws.tester_lock(tmp_path, wait=True):
        pass
    assert len(calls) == 2


def test_lock_of_a_killed_holder_is_free(tmp_path):
    import subprocess
    import sys
    import time

    code = ("import sys, time; from pathlib import Path; from mt5_mcp.mql5 import workspace as ws\n"
            "with ws.tester_lock(Path(sys.argv[1])):\n    print('locked', flush=True); time.sleep(60)")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    p = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, text=True, env=env)
    try:
        assert p.stdout.readline().strip() == "locked"
        with pytest.raises(ws.LockHeld):
            with ws.tester_lock(tmp_path):
                pass
        p.kill()
        p.wait()
        deadline = time.monotonic() + 10  # Windows frees a dead process's lock asynchronously
        while True:
            try:
                with ws.tester_lock(tmp_path):
                    break
            except ws.LockHeld:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
    finally:
        p.kill()
