"""Shared fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.fakes import FakeMT5


@pytest.fixture
def fake_mt5() -> FakeMT5:
    return FakeMT5()


@pytest.fixture
def frozen_utc(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Pin UTC 'now' to 2026-04-21T10:00:00Z for deterministic TZ-offset tests."""
    fixed = datetime(2026, 4, 21, 10, 0, 0, tzinfo=timezone.utc)

    class _Clock:
        @staticmethod
        def now(tz: timezone | None = None) -> datetime:
            return fixed if tz else fixed.replace(tzinfo=None)

        @staticmethod
        def fromtimestamp(ts: float, tz: timezone | None = None) -> datetime:
            return datetime.fromtimestamp(ts, tz=tz)

    monkeypatch.setattr("mt5_mcp.adapter.mt5_client.datetime", _Clock)
    monkeypatch.setattr("mt5_mcp.adapter.conversions.datetime", _Clock)
    return fixed


@pytest.fixture(autouse=True)
def _reset_app_context():
    """Ensure each test starts with a clean app-context singleton.

    The mt5_mcp.server module holds a process-wide AppContext for handler
    convenience. Clearing it between tests prevents one test's mt5_module
    injection from leaking into the next.
    """
    from mt5_mcp.server import reset_context_for_tests

    reset_context_for_tests()
    yield
    reset_context_for_tests()
