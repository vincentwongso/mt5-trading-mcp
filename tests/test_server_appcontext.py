"""Tests for Dispatcher + Poller wiring in AppContext (Phase 3, Task 9)."""

from pathlib import Path


from mt5_mcp.server import build_context, reset_context_for_tests
from mt5_mcp.streaming.dispatcher import Dispatcher
from mt5_mcp.streaming.poller import Poller
from tests.fakes import FakeMT5


def _cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[idempotency]\npath = "{(tmp_path / "idem.db").as_posix()}"\n'
        f'[audit]\npath = "{(tmp_path / "audit.jsonl").as_posix()}"\n'
    )
    return cfg


def test_appcontext_has_dispatcher_and_poller(tmp_path):
    fake = FakeMT5()
    ctx = build_context(config_path=_cfg(tmp_path), mt5_module=fake)
    assert isinstance(ctx.dispatcher, Dispatcher)
    assert isinstance(ctx.poller, Poller)


def test_appcontext_dispatcher_bound_to_poller(tmp_path):
    fake = FakeMT5()
    ctx = build_context(config_path=_cfg(tmp_path), mt5_module=fake)
    # Dispatcher delegates start to poller; we verify by checking the bind.
    assert ctx.dispatcher._poller is ctx.poller  # type: ignore[attr-defined]


def test_reset_context_stops_running_poller(tmp_path):
    fake = FakeMT5()
    ctx = build_context(config_path=_cfg(tmp_path), mt5_module=fake)
    ctx.poller.start()
    reset_context_for_tests()
    # After reset, the thread must have exited.
    assert ctx.poller._thread is None  # type: ignore[attr-defined]
