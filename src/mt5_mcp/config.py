"""Configuration model + TOML loader + watchdog-driven hot reload."""

from __future__ import annotations

import logging
import os
import sys
import threading
from decimal import Decimal
from pathlib import Path
from typing import Literal
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


class BridgeConfig(_Sub):
    """RPyC bridge to an MT5 terminal running elsewhere (e.g. the
    gmag11/metatrader5_vnc Docker container on Linux). When present, the
    adapter connects via an mt5linux client instead of importing the
    Windows-only MetaTrader5 package in-process."""
    host: str = "127.0.0.1"
    port: int = Field(8001, ge=1, le=65535)


class MT5Section(_Sub):
    terminal_path: str = ""
    # Programmatic-login credentials for headless / container deployments.
    # When `login` is set, the adapter authenticates via initialize(login=,
    # password=, server=) instead of attaching to an already-logged-in
    # terminal. `MT5_LOGIN` / `MT5_SERVER` env vars override these values
    # (see `load_config`). There is deliberately NO `password` field - the
    # password is env-only (`MT5_PASSWORD`) so it never lands in a config file
    # or a serialized Config object.
    login: int | None = None
    server: str | None = None
    # Presence of this block selects the RPyC bridge backend; omit it for the
    # native (Windows-native or Wine-prefix Python) in-process backend.
    bridge: BridgeConfig | None = None
    # Connect to MT5 at server startup (on the main thread, before the stdio/HTTP
    # loop) instead of lazily on the first tool call. FastMCP runs sync tool
    # handlers inline on the asyncio event-loop thread, where the MetaTrader5
    # C-extension's first import + initialize() can take minutes - long enough to
    # trip stdio-client timeouts (Claude Desktop / Claude Code). The same connect
    # runs in well under a second on the main thread, so doing it eagerly at
    # startup keeps the first tool call fast. If the startup connect fails (e.g.
    # the terminal isn't up yet) the server still starts and falls back to the
    # lazy connect on first use. On by default; disable with
    # `serve --no-eager-connect` or `[mt5] eager_connect = false`.
    eager_connect: bool = True


class PolicySection(_Sub):
    # All Decimals - the architecture insists no floats on money amounts.
    # Consent gate master switch. 0 (the default) = OFF: mutating calls
    # auto-execute (full-open, intended for trusted/unattended agents). Set it
    # > 0 to arm the gate: place_order / close_position then require human
    # approval when notional is at or above it, and modify_order requires
    # approval to widen/remove a stop. Every limit below is likewise opt-in
    # (0 / empty = off).
    auto_approve_notional: Decimal = Decimal("0")
    max_notional_per_trade: Decimal = Decimal("0")
    max_realised_loss_per_close: Decimal = Decimal("0")
    max_daily_loss: Decimal = Decimal("0")
    # Consent retry window.
    approval_ttl_seconds: PositiveInt = 300
    # Sliding-window cap on place_order executions per 60s (0 = no cap). A brake
    # on a runaway/looping agent, independent of the consent gate.
    max_orders_per_minute: int = Field(default=0, ge=0)


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
    # Stateless HTTP: handle every request with a fresh, immediately torn-down
    # transport instead of persisting one transport per MCP session. ON by
    # default because it is the correct posture for the dominant HTTP usage -
    # an agent that opens a session per poll and never tears it down. In stateful
    # mode (stateless = false) each such session leaks a StreamableHTTPServer
    # transport (held in the SDK's _server_instances map until a clean DELETE),
    # so a polling client grows the process unbounded. The trade-off: stateless
    # mode cannot push server-initiated notifications, so resource subscriptions
    # (the [streaming] quotes/account/positions push) are inert over HTTP - tools
    # still work, clients just poll instead of being pushed to. Set false only if
    # a client genuinely subscribes for live updates. No effect on stdio.
    stateless: bool = True
    # Hostnames to add to FastMCP's DNS-rebinding-protection allow list.
    # FastMCP defaults already include 127.0.0.1, localhost, [::1] (with
    # wildcard ports). Add entries here when the MCP sits behind a reverse
    # proxy that forwards a non-loopback Host header - e.g. Tailscale serve
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


class LoggingSection(_Sub):
    # Root log level for the server. Defaults to WARNING so an unattended HTTP
    # deployment stays quiet: WARNING silences uvicorn's per-request access log,
    # the SDK's "Processing request of type CallToolRequest" line, and the
    # transport-creation chatter - while still surfacing the consent-posture and
    # auth warnings. Set "INFO" for normal operational logging or "DEBUG" to
    # trace everything. Overridden by `MT5_MCP_LOG_LEVEL` (env) and
    # `serve --log-level` (CLI); CLI wins, then env, then this value.
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"


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
    logging: LoggingSection = Field(default_factory=LoggingSection)


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
    """Load + validate a config file, then overlay credential env vars.

    If `path` is None and the default location is absent, returns a
    Config with defaults so the server can still start for smoke testing.
    `MT5_LOGIN` / `MT5_SERVER` env vars always override the file (env wins);
    see `_apply_mt5_env_overrides`.
    """
    config = _read_config_file(path)
    _apply_mt5_env_overrides(config)
    _apply_logging_env_override(config)
    return config


def _read_config_file(path: Path | None) -> Config:
    if path is None:
        path = default_config_path()
        if not path.exists():
            logger.info("no config file at %s; using defaults", path)
            return Config()
    if not path.exists():
        raise FileNotFoundError(path)
    # `utf-8-sig` strips a leading UTF-8 BOM (EF BB BF) if present; otherwise
    # behaves identically to `utf-8`. Notepad and Windows PowerShell 5.1's
    # `Set-Content -Encoding UTF8` both write BOMs by default - without this
    # the user gets a confusing `tomllib.TOMLDecodeError: Invalid statement
    # (at line 1, column 1)` because the BOM bytes parse as garbage before
    # the first `[`.
    raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    try:
        return Config(**raw)
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"invalid config at {path}: {exc}") from exc


def _apply_mt5_env_overrides(config: Config) -> None:
    """Overlay `MT5_LOGIN` / `MT5_SERVER` onto the `[mt5]` section (env wins).

    The password is deliberately NOT read here - it is resolved at connect
    time, env-only (`MT5_PASSWORD`), so it never lands in a Config object that
    could be logged or serialized. Empty-string env vars are treated as unset.
    """
    login_env = os.environ.get("MT5_LOGIN")
    if login_env:
        try:
            config.mt5.login = int(login_env)
        except ValueError as exc:
            raise ValueError(
                f"MT5_LOGIN must be an integer account number, got {login_env!r}"
            ) from exc
    server_env = os.environ.get("MT5_SERVER")
    if server_env:
        config.mt5.server = server_env


def _apply_logging_env_override(config: Config) -> None:
    """Overlay `MT5_MCP_LOG_LEVEL` onto `[logging] level` (env wins over file).

    Empty / unset is ignored. An unrecognised level raises, so a typo fails
    loudly at startup rather than silently defaulting.
    """
    level_env = os.environ.get("MT5_MCP_LOG_LEVEL")
    if not level_env:
        return
    level = level_env.strip().upper()
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level not in valid:
        raise ValueError(
            f"MT5_MCP_LOG_LEVEL must be one of {sorted(valid)}, got {level_env!r}"
        )
    config.logging.level = level  # type: ignore[assignment]


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

    A broken reload (invalid TOML, schema violation) is logged and ignored -
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
