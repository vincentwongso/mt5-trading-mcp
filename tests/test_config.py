"""Config loader + hot-reload."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.config import Config, ConfigWatcher, load_config


MINIMAL_TOML = """
[mt5]
terminal_path = ""

[policy]
auto_approve_notional = "1000.00"
max_notional_per_trade = "10000.00"
max_realised_loss_per_close = "500.00"
max_daily_loss = "2000.00"

[idempotency]
ttl_seconds = 86400

[symbols]
allowlist = []
denylist = []

[audit]
path = "/tmp/test-audit.jsonl"
max_bytes = 10485760

[transport.http]
auth_token = ""

[telemetry]
enabled = false
endpoint = ""
"""


def test_load_valid_config(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.policy.auto_approve_notional == Decimal("1000.00")
    assert cfg.idempotency.ttl_seconds == 86400
    assert cfg.telemetry.enabled is False


def test_load_rejects_invalid(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML.replace('ttl_seconds = 86400', 'ttl_seconds = -1'))
    with pytest.raises(ValueError):
        load_config(p)


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_load_default_location(monkeypatch, tmp_path: Path):
    """When no path is given, falls back to `%APPDATA%\\mt5-mcp\\config.toml`
    (or the XDG equivalent). If that file doesn't exist either, returns a
    Config populated with defaults."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()  # no argument; no file on disk → defaults
    assert isinstance(cfg, Config)
    assert cfg.policy.auto_approve_notional == Decimal("0")  # default


def test_hot_reload_picks_up_changes(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)

    watcher = ConfigWatcher(p)
    watcher.start()
    try:
        assert watcher.current.idempotency.ttl_seconds == 86400

        p.write_text(MINIMAL_TOML.replace("ttl_seconds = 86400", "ttl_seconds = 60"))
        # Poll watcher up to 2s for the new value.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if watcher.current.idempotency.ttl_seconds == 60:
                break
            time.sleep(0.05)
        assert watcher.current.idempotency.ttl_seconds == 60
    finally:
        watcher.stop()


def test_reload_survives_broken_edit(tmp_path: Path, caplog):
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)

    watcher = ConfigWatcher(p)
    watcher.start()
    try:
        original = watcher.current

        # Write garbage — reload should fail, warn, and retain the previous config.
        p.write_text("not valid [[ toml")
        time.sleep(0.5)
        assert watcher.current is original
    finally:
        watcher.stop()


def test_default_idempotency_path_uses_platformdirs():
    from mt5_mcp.config import Config

    cfg = Config()
    p = cfg.idempotency.path
    assert p.endswith("idempotency.db") or p.endswith("idempotency.db".replace("/", "\\"))
    assert p.count("mt5-mcp") == 1, f"expected one 'mt5-mcp' segment, got: {p}"


def test_default_audit_path_uses_platformdirs():
    from mt5_mcp.config import Config

    cfg = Config()
    p = cfg.audit.path
    assert p.endswith("audit.jsonl") or p.endswith("audit.jsonl".replace("/", "\\"))
    assert p.count("mt5-mcp") == 1, f"expected one 'mt5-mcp' segment, got: {p}"


def test_idempotency_path_is_overridable_in_toml(tmp_path):
    import textwrap
    from mt5_mcp.config import load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [idempotency]
        path = "/custom/path/idem.db"
        ttl_seconds = 3600

        [audit]
        path = "/custom/path/audit.jsonl"
        max_bytes = 1048576
    """).strip())
    cfg = load_config(cfg_file)
    assert cfg.idempotency.path == "/custom/path/idem.db"
    assert cfg.idempotency.ttl_seconds == 3600
    assert cfg.audit.path == "/custom/path/audit.jsonl"
    assert cfg.audit.max_bytes == 1048576
