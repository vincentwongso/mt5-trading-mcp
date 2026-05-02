"""Configuration model + TOML loader + watchdog-driven hot reload."""

from __future__ import annotations

import logging
import os
import sys
import threading
from decimal import Decimal
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import]
else:
    import tomli as tomllib  # type: ignore[import]


logger = logging.getLogger(__name__)


class _Sub(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _user_data_path(filename: str) -> str:
    """Per-OS default path under platformdirs.user_data_dir('mt5-mcp')."""
    from platformdirs import user_data_dir

    return str(Path(user_data_dir("mt5-mcp", appauthor=False)) / filename)


class MT5Section(_Sub):
    terminal_path: str = ""
    preferred_login: int | None = None


class PolicySection(_Sub):
    # All Decimals — the architecture insists no floats on money amounts.
    auto_approve_notional: Decimal = Decimal("0")
    max_notional_per_trade: Decimal = Decimal("0")
    max_realised_loss_per_close: Decimal = Decimal("0")
    max_daily_loss: Decimal = Decimal("0")
    # Consent retry window; re-used by Phase 2.
    approval_ttl_seconds: PositiveInt = 300


class IdempotencySection(_Sub):
    path: str = Field(default_factory=lambda: _user_data_path("idempotency.db"))
    ttl_seconds: PositiveInt = 86_400


class SymbolsSection(_Sub):
    allowlist: list[str] = Field(default_factory=list)
    denylist: list[str] = Field(default_factory=list)


class AuditSection(_Sub):
    path: str = Field(default_factory=lambda: _user_data_path("audit.jsonl"))
    max_bytes: PositiveInt = 10_485_760


class TransportHTTPSection(_Sub):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    auth_token: str = ""
    # Hostnames to add to FastMCP's DNS-rebinding-protection allow list.
    # FastMCP defaults already include 127.0.0.1, localhost, [::1] (with
    # wildcard ports). Add entries here when the MCP sits behind a reverse
    # proxy that forwards a non-loopback Host header — e.g. Tailscale serve
    # at https://<machine>.<tailnet>.ts.net.
    trusted_hosts: list[str] = Field(default_factory=list)
    trusted_origins: list[str] = Field(default_factory=list)


class TransportSection(_Sub):
    http: TransportHTTPSection = Field(default_factory=TransportHTTPSection)


class TelemetrySection(_Sub):
    enabled: bool = False
    endpoint: str = ""


class StreamingSection(_Sub):
    quote_poll_interval_ms: int = Field(200, ge=50, le=10000)
    account_poll_interval_ms: int = Field(1000, ge=100, le=60000)
    positions_poll_interval_ms: int = Field(1000, ge=100, le=60000)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mt5: MT5Section = Field(default_factory=MT5Section)
    policy: PolicySection = Field(default_factory=PolicySection)
    idempotency: IdempotencySection = Field(default_factory=IdempotencySection)
    symbols: SymbolsSection = Field(default_factory=SymbolsSection)
    audit: AuditSection = Field(default_factory=AuditSection)
    transport: TransportSection = Field(default_factory=TransportSection)
    telemetry: TelemetrySection = Field(default_factory=TelemetrySection)
    streaming: StreamingSection = Field(default_factory=StreamingSection)


def default_config_path() -> Path:
    """Resolve the OS-default config file path.

    Windows: `%APPDATA%\\mt5-mcp\\config.toml`.
    Linux / WSL2: `$XDG_CONFIG_HOME/mt5-mcp/config.toml` or
    `~/.config/mt5-mcp/config.toml`.
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "mt5-mcp" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load + validate a config file.

    If `path` is None and the default location is absent, returns a
    Config with defaults so the server can still start for smoke testing.
    """
    if path is None:
        path = default_config_path()
        if not path.exists():
            logger.info("no config file at %s; using defaults", path)
            return Config()
    if not path.exists():
        raise FileNotFoundError(path)
    # `utf-8-sig` strips a leading UTF-8 BOM (EF BB BF) if present; otherwise
    # behaves identically to `utf-8`. Notepad and Windows PowerShell 5.1's
    # `Set-Content -Encoding UTF8` both write BOMs by default — without this
    # the user gets a confusing `tomllib.TOMLDecodeError: Invalid statement
    # (at line 1, column 1)` because the BOM bytes parse as garbage before
    # the first `[`.
    raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    try:
        return Config(**raw)
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"invalid config at {path}: {exc}") from exc


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, path: Path, on_change) -> None:
        self._path = path.resolve()
        self._on_change = on_change

    def on_modified(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        if not event.is_directory and Path(event.src_path).resolve() == self._path:
            self._on_change()

    # Some editors rename-and-replace on save; catch that too.
    def on_moved(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        dest = getattr(event, "dest_path", None)
        if dest and Path(dest).resolve() == self._path:
            self._on_change()


class ConfigWatcher:
    """Watches the config file and reloads on change.

    A broken reload (invalid TOML, schema violation) is logged and ignored —
    `.current` keeps the last-good config so the running server isn't
    destabilised by a typo.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._current = load_config(path)
        self._observer: Observer | None = None

    @property
    def current(self) -> Config:
        with self._lock:
            return self._current

    def reload(self) -> None:
        try:
            new = load_config(self._path)
        except Exception as exc:
            logger.warning("config reload failed, keeping previous: %s", exc)
            return
        with self._lock:
            self._current = new
        logger.info("config reloaded from %s", self._path)

    def start(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        self._observer.schedule(
            _ReloadHandler(self._path, self.reload),
            str(self._path.parent),
            recursive=False,
        )
        self._observer.start()

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2.0)
        self._observer = None
