"""Finding MetaEditor and the terminal data folder without a running terminal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mt5_mcp.mql5.terminal import LocateError, TerminalPaths, locate_terminal


def make_install(d: Path, *, mql5: bool = False) -> Path:
    d.mkdir(parents=True)
    (d / "terminal64.exe").write_bytes(b"")
    (d / "metaeditor64.exe").write_bytes(b"")
    if mql5:
        (d / "MQL5").mkdir()
    return d


def make_data(appdata: Path, terminal_id: str, origin: str, log_mtime: float | None = None) -> Path:
    d = appdata / "MetaQuotes" / "Terminal" / terminal_id
    (d / "MQL5").mkdir(parents=True)
    (d / "origin.txt").write_bytes(("﻿" + origin).encode("utf-16-le"))
    if log_mtime is not None:
        add_log(d, log_mtime)
    return d


def add_log(d: Path, mtime: float) -> None:
    (d / "logs").mkdir(exist_ok=True)
    f = d / "logs" / "20261120.log"
    f.write_bytes(b"x")
    os.utime(f, (mtime, mtime))


@pytest.fixture
def pf(tmp_path: Path) -> Path:
    return tmp_path / "Program Files"


@pytest.fixture
def appdata(tmp_path: Path) -> Path:
    return tmp_path / "AppData" / "Roaming"


def test_explicit_terminal_path_exe_or_folder(pf, appdata):
    inst = make_install(pf / "MetaTrader 5")
    data = make_data(appdata, "A", str(inst))
    want = TerminalPaths(inst, inst / "metaeditor64.exe", data)
    for tp in (str(inst / "terminal64.exe"), str(inst)):
        assert locate_terminal(terminal_path=tp, program_files=[], appdata=appdata) == want


def test_explicit_data_path_wins(pf, appdata, tmp_path):
    inst = make_install(pf / "MetaTrader 5")
    make_data(appdata, "A", str(inst), log_mtime=2e9)
    other = tmp_path / "elsewhere"
    (other / "MQL5").mkdir(parents=True)
    got = locate_terminal(data_path=str(other), program_files=[pf], appdata=appdata)
    assert got.data_dir == other


def test_explicit_data_path_without_mql5_raises(pf, appdata, tmp_path):
    make_install(pf / "MetaTrader 5")
    with pytest.raises(LocateError, match="MQL5"):
        locate_terminal(data_path=str(tmp_path), program_files=[pf], appdata=appdata)


def test_autodetect_single_install_under_program_files(pf, tmp_path, appdata):
    x86 = tmp_path / "Program Files (x86)"
    inst = make_install(x86 / "Broker MT5")
    data = make_data(appdata, "A", str(inst))
    got = locate_terminal(program_files=[pf, x86], appdata=appdata)
    assert (got.install_dir, got.metaeditor, got.data_dir) == (inst, inst / "metaeditor64.exe", data)


def test_two_installs_without_terminal_path_is_ambiguous(pf, appdata):
    a = make_install(pf / "MetaTrader 5")
    b = make_install(pf / "Fusion Markets MetaTrader 5")
    with pytest.raises(LocateError) as exc:
        locate_terminal(program_files=[pf], appdata=appdata)
    msg = str(exc.value)
    assert str(a) in msg and str(b) in msg and "terminal_path" in msg


def test_no_metaeditor_raises(pf, appdata):
    inst = pf / "MetaTrader 5"
    inst.mkdir(parents=True)
    (inst / "terminal64.exe").write_bytes(b"")
    with pytest.raises(LocateError, match="metaeditor64.exe"):
        locate_terminal(terminal_path=str(inst), program_files=[], appdata=appdata)


def test_nothing_installed_raises(pf, appdata):
    with pytest.raises(LocateError, match="terminal_path"):
        locate_terminal(program_files=[pf], appdata=appdata)


def test_data_from_origin_txt_ignores_case_and_trailing_slash(pf, appdata):
    inst = make_install(pf / "MetaTrader 5")
    make_data(appdata, "OTHER", str(pf / "Something Else"))
    data = make_data(appdata, "A", str(inst).upper() + os.sep)
    got = locate_terminal(terminal_path=str(inst), program_files=[], appdata=appdata)
    assert got.data_dir == data


def test_portable_install_folder(pf, appdata):
    inst = make_install(pf / "MT5", mql5=True)
    got = locate_terminal(terminal_path=str(inst), program_files=[], appdata=appdata)
    assert got.data_dir == inst


def test_portable_without_appdata(pf):
    inst = make_install(pf / "MT5", mql5=True)
    assert locate_terminal(terminal_path=str(inst), program_files=[], appdata=None).data_dir == inst


@pytest.mark.parametrize("install_newer", [True, False])
def test_newest_logs_wins_when_both(pf, appdata, install_newer):
    inst = make_install(pf / "MT5", mql5=True)
    add_log(inst, 2e9 if install_newer else 1e9)
    data = make_data(appdata, "A", str(inst), log_mtime=1e9 if install_newer else 2e9)
    got = locate_terminal(terminal_path=str(inst), program_files=[], appdata=appdata)
    assert got.data_dir == (inst if install_newer else data)


def test_several_candidates_without_logs_is_ambiguous(pf, appdata):
    inst = make_install(pf / "MT5", mql5=True)
    make_data(appdata, "A", str(inst))
    with pytest.raises(LocateError, match="data_path"):
        locate_terminal(terminal_path=str(inst), program_files=[], appdata=appdata)


def test_no_data_folder_raises(pf, appdata):
    inst = make_install(pf / "MetaTrader 5")
    with pytest.raises(LocateError, match="data_path"):
        locate_terminal(terminal_path=str(inst), program_files=[], appdata=appdata)


def test_relative_paths_are_made_absolute(pf, appdata, monkeypatch, tmp_path):
    inst = make_install(pf / "MetaTrader 5")
    data = make_data(appdata, "A", str(inst))
    monkeypatch.chdir(tmp_path)
    got = locate_terminal(terminal_path=str(inst.relative_to(tmp_path)), program_files=[], appdata=appdata)
    assert got.install_dir.is_absolute() and got.data_dir == data
    rel = locate_terminal(terminal_path=str(inst), data_path=str(data.relative_to(tmp_path)), program_files=[], appdata=appdata)
    assert rel.data_dir == data
