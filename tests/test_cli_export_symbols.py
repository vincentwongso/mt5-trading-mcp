"""export-symbols CLI."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from mt5_mcp.cli.export_symbols import run_export
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo


def test_export_writes_csv_with_all_symbols(tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbols_get = (
        FakeSymbolInfo(name="EURUSD", path="Forex\\Majors\\EURUSD"),
        FakeSymbolInfo(name="XAUUSD", path="Metals\\XAUUSD"),
    )
    out = tmp_path / "symbols.csv"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    rc = run_export(output=out, mt5_module=fake, config_path=cfg)
    assert rc == 0

    with out.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["name"] for r in rows} == {"EURUSD", "XAUUSD"}
    assert {r["category"] for r in rows} == {"Forex", "Metals"}
    # spot-check one numeric column round-trips as string
    assert rows[0]["volume_step"] == "0.01"


def test_export_exits_nonzero_when_disconnected(tmp_path: Path):
    fake = FakeMT5()
    fake._terminal_info = None
    out = tmp_path / "symbols.csv"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    rc = run_export(output=out, mt5_module=fake, config_path=cfg)
    assert rc != 0
