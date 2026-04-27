from datetime import datetime, timezone
from pathlib import Path

import pytest

from mt5_mcp.cli.doctor import run_doctor
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo, FakeTick


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
        '[streaming]\nquote_poll_interval_ms = 50\n'
    )
    return cfg


def test_doctor_streaming_check_passes_with_active_tick(tmp_path, capsys):
    fake = FakeMT5()
    fake._terminal_info = FakeTerminalInfo(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp())
    )
    fake._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    fake._symbol_info_tick["EURUSD"] = FakeTick(
        time=int(datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc).timestamp()),
        bid=1.0823, ask=1.0824,
    )
    rc = run_doctor(mt5_module=fake, probe_symbol="EURUSD",
                    config_path=_config(tmp_path), check_streaming=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "[PASS] streaming" in out
