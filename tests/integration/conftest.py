"""Fixtures and helpers for the Phase 5 live-broker integration suite.

This conftest overrides the unit-suite's autouse `_reset_app_context` so
the session-scope `live_server` (added in Task 2) can build the AppContext
once and reuse it across the integration session.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_app_context():
    """Override the unit-test autouse reset.

    The parent `tests/conftest.py` wipes the singleton AppContext between
    tests so unit tests can swap their FakeMT5 instances. Integration tests
    share one live MT5 connection across the session and MUST NOT have it
    torn down between tests. Tear-down happens in `live_server` teardown.
    """
    yield
