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


def test_load_strips_utf8_bom(tmp_path: Path):
    """Config files written by Notepad / `Set-Content -Encoding UTF8` on
    Windows PS 5.1 carry a UTF-8 BOM. `tomllib` rejects BOMs as syntax
    errors, so `load_config` must read with `utf-8-sig` to strip them."""
    p = tmp_path / "config.toml"
    # Write the BOM bytes (EF BB BF) followed by a valid minimal TOML body.
    p.write_bytes(b"\xef\xbb\xbf" + MINIMAL_TOML.encode("utf-8"))
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    # Same field as the no-BOM happy-path test, proving the BOM was stripped
    # before parsing rather than just suppressed.
    assert cfg.policy.auto_approve_notional == Decimal("1000.00")


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

        # Write garbage - reload should fail, warn, and retain the previous config.
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


def test_config_defaults_have_http_host_port_and_streaming(tmp_path):
    cfg = Config()
    assert cfg.transport.http.host == "127.0.0.1"
    assert cfg.transport.http.port == 8765
    assert cfg.transport.http.auth_token == ""
    assert cfg.streaming.quote_poll_interval_ms == 200
    assert cfg.streaming.account_poll_interval_ms == 1000
    assert cfg.streaming.positions_poll_interval_ms == 1000


def test_config_streaming_intervals_have_floor_and_ceiling(tmp_path):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Config(streaming={"quote_poll_interval_ms": 10})  # below 50ms floor
    with pytest.raises(ValidationError):
        Config(streaming={"quote_poll_interval_ms": 99999})  # above 10000ms


def test_config_loads_streaming_and_transport_from_toml(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[transport.http]\n'
        'host = "127.0.0.1"\n'
        'port = 9000\n'
        'auth_token = "secret"\n'
        '[streaming]\n'
        'quote_poll_interval_ms = 100\n'
        'account_poll_interval_ms = 500\n'
        'positions_poll_interval_ms = 500\n'
    )
    cfg = load_config(cfg_file)
    assert cfg.transport.http.port == 9000
    assert cfg.transport.http.auth_token == "secret"
    assert cfg.streaming.quote_poll_interval_ms == 100


def test_mt5_bridge_absent_defaults_to_none(tmp_path):
    from mt5_mcp.config import load_config
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[mt5]\nterminal_path = \"\"\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.mt5.bridge is None


def test_mt5_bridge_parses_host_and_port(tmp_path):
    from mt5_mcp.config import load_config
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        "[mt5.bridge]\nhost = \"10.0.0.5\"\nport = 8001\n", encoding="utf-8"
    )
    cfg = load_config(cfg_file)
    assert cfg.mt5.bridge is not None
    assert cfg.mt5.bridge.host == "10.0.0.5"
    assert cfg.mt5.bridge.port == 8001


def test_mt5_bridge_defaults(tmp_path):
    from mt5_mcp.config import load_config
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[mt5.bridge]\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.mt5.bridge.host == "127.0.0.1"
    assert cfg.mt5.bridge.port == 8001


def test_mt5_bridge_rejects_bad_port(tmp_path):
    from mt5_mcp.config import load_config
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[mt5.bridge]\nport = 0\n", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        load_config(cfg_file)


# --- programmatic-login credentials (Task 2) ----------------------------


def test_mt5_login_server_from_config_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.delenv("MT5_SERVER", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[mt5]\nlogin = 7000592\nserver = "Fintrix-Live"\n', encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.mt5.login == 7000592
    assert cfg.mt5.server == "Fintrix-Live"


def test_mt5_login_server_env_overrides_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[mt5]\nlogin = 111\nserver = "Cfg-Server"\n', encoding="utf-8")
    monkeypatch.setenv("MT5_LOGIN", "999")
    monkeypatch.setenv("MT5_SERVER", "Env-Server")
    cfg = load_config(cfg_file)
    assert cfg.mt5.login == 999
    assert cfg.mt5.server == "Env-Server"


def test_mt5_login_server_from_env_when_no_config_keys(tmp_path, monkeypatch):
    """The container path: creds arrive purely via env, no [mt5] keys."""
    monkeypatch.setenv("MT5_LOGIN", "7000592")
    monkeypatch.setenv("MT5_SERVER", "Fintrix-Live")
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.mt5.login == 7000592
    assert cfg.mt5.server == "Fintrix-Live"


def test_mt5_login_defaults_none_without_env_or_config(tmp_path, monkeypatch):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.delenv("MT5_SERVER", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.mt5.login is None
    assert cfg.mt5.server is None


def test_mt5_login_env_must_be_integer(tmp_path, monkeypatch):
    monkeypatch.setenv("MT5_LOGIN", "not-a-number")
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg_file)


def test_mt5_password_field_rejected_in_config(tmp_path):
    """Password must NEVER be a config key - env-only by design."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[mt5]\npassword = "leak"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg_file)


def test_mt5_password_env_not_loaded_into_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MT5_PASSWORD", "topsecret")
    monkeypatch.setenv("MT5_LOGIN", "7000592")
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert not hasattr(cfg.mt5, "password")
    assert "topsecret" not in cfg.model_dump_json()
