"""Unit tests for the file-bridge to the AgentScreenshot MQL5 EA.

No real EA runs here: we stand in for it by pre-seeding the response files
under the fake terminal data_path, using a fixed request id.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mt5_mcp.adapter.screenshot import capture_chart
from mt5_mcp.errors import MT5Error


class _StubClient:
    """Minimal stand-in for MT5Client: client.call(fn) -> fn(mt5_module),
    and mt5_module.terminal_info().data_path points at a temp folder."""

    def __init__(self, data_path: Path):
        self._mt5 = SimpleNamespace(
            terminal_info=lambda: SimpleNamespace(data_path=str(data_path))
        )

    def call(self, fn):
        return fn(self._mt5)


def _files_dir(root: Path) -> Path:
    d = root / "MQL5" / "Files" / "agent_screenshot"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_happy_path_returns_png_and_cleans_up(tmp_path):
    d = _files_dir(tmp_path)
    (d / "fixedid.png").write_bytes(b"PNGBYTES")
    (d / "fixedid.done").write_text("ok", encoding="utf-16-le")

    out = capture_chart(
        _StubClient(tmp_path),
        symbol="XAUUSD.z",
        timeframe_name="H1",
        width=800,
        height=600,
        template=None,
        timeout_s=1.0,
        id_factory=lambda: "fixedid",
    )

    assert out == b"PNGBYTES"
    # All bridge files removed afterwards (req, done, png, tmp).
    assert list(d.iterdir()) == []


def test_bom_prefixed_ok_status_is_tolerated(tmp_path):
    # MQL5 FileWriteString(FILE_UNICODE) prepends a UTF-16 BOM to newly
    # created files, so a real EA's "ok" status arrives as "﻿ok".
    d = _files_dir(tmp_path)
    (d / "fixedid.png").write_bytes(b"PNGBYTES")
    (d / "fixedid.done").write_text("﻿ok", encoding="utf-16-le")

    out = capture_chart(
        _StubClient(tmp_path),
        symbol="XAUUSD.z",
        timeframe_name="H1",
        width=800,
        height=600,
        template=None,
        timeout_s=1.0,
        id_factory=lambda: "fixedid",
    )

    assert out == b"PNGBYTES"


def test_request_payload_is_written(tmp_path):
    d = _files_dir(tmp_path)
    seen = {}

    def fake_sleep(_):
        # Stand in for the EA: on the first poll, read the request line and
        # seed the response, so we assert exactly what capture_chart wrote.
        if not seen:
            seen["payload"] = (d / "fixedid.req").read_text(encoding="utf-16-le")
            (d / "fixedid.png").write_bytes(b"X")
            (d / "fixedid.done").write_text("ok", encoding="utf-16-le")

    out = capture_chart(
        _StubClient(tmp_path),
        symbol="EURUSD.z",
        timeframe_name="M15",
        width=1280,
        height=720,
        template="agent.tpl",
        timeout_s=1.0,
        poll_interval_s=0.01,
        id_factory=lambda: "fixedid",
        sleep=fake_sleep,
    )
    assert out == b"X"
    assert seen["payload"] == "fixedid|EURUSD.z|M15|1280|720|agent.tpl"


def test_timeout_raises(tmp_path):
    _files_dir(tmp_path)  # dir exists but no .done ever appears
    with pytest.raises(MT5Error) as ei:
        capture_chart(
            _StubClient(tmp_path),
            symbol="EURUSD.z",
            timeframe_name="H1",
            width=800,
            height=600,
            template=None,
            timeout_s=0.3,
            poll_interval_s=0.05,
            id_factory=lambda: "fixedid",
        )
    assert ei.value.detail.code == "SCREENSHOT_TIMEOUT"
    assert ei.value.detail.retryable is True


def test_ea_error_raises_failed(tmp_path):
    d = _files_dir(tmp_path)
    (d / "fixedid.done").write_text("err:ChartOpen failed", encoding="utf-16-le")
    with pytest.raises(MT5Error) as ei:
        capture_chart(
            _StubClient(tmp_path),
            symbol="BADSYM",
            timeframe_name="H1",
            width=800,
            height=600,
            template=None,
            timeout_s=1.0,
            id_factory=lambda: "fixedid",
        )
    assert ei.value.detail.code == "SCREENSHOT_FAILED"
    assert "ChartOpen failed" in ei.value.detail.message


def test_stale_orphans_are_swept(tmp_path):
    import os
    d = _files_dir(tmp_path)
    orphan = d / "old.png"
    orphan.write_bytes(b"OLD")
    os.utime(orphan, (1_000_000.0, 1_000_000.0))  # ancient mtime
    # Fresh in-flight response for the happy path (must NOT be swept).
    (d / "fixedid.png").write_bytes(b"PNGBYTES")
    (d / "fixedid.done").write_text("ok", encoding="utf-16-le")

    out = capture_chart(
        _StubClient(tmp_path),
        symbol="EURUSD.z",
        timeframe_name="H1",
        width=800,
        height=600,
        template=None,
        timeout_s=1.0,
        id_factory=lambda: "fixedid",
        stale_ttl_s=300.0,
    )
    assert out == b"PNGBYTES"        # fresh files were used, not swept
    assert not orphan.exists()       # ancient orphan removed


def test_sweep_ttl_respects_long_timeout(tmp_path):
    # A user timeout_s above the stale_ttl_s floor must not let the sweep
    # remove a concurrent call's still-in-flight files (age < timeout_s).
    import os

    d = _files_dir(tmp_path)
    now = 10_000.0
    inflight = d / "concurrent.req"
    inflight.write_text("x", encoding="utf-16-le")
    os.utime(inflight, (now - 10, now - 10))     # 10s old, within a 100s timeout
    ancient = d / "ancient.png"
    ancient.write_bytes(b"OLD")
    os.utime(ancient, (now - 5000, now - 5000))  # far older than timeout + buffer
    (d / "fixedid.png").write_bytes(b"PNGBYTES")
    (d / "fixedid.done").write_text("ok", encoding="utf-16-le")

    out = capture_chart(
        _StubClient(tmp_path),
        symbol="EURUSD.z",
        timeframe_name="H1",
        width=800,
        height=600,
        template=None,
        timeout_s=100.0,          # exceeds the 1.0s stale floor below
        stale_ttl_s=1.0,
        id_factory=lambda: "fixedid",
        wall_clock=lambda: now,
    )
    assert out == b"PNGBYTES"
    assert inflight.exists()      # not swept: within the in-flight window
    assert not ancient.exists()   # swept: far older than timeout + buffer


def test_missing_data_path_raises_failed(tmp_path):
    class _NoPath:
        def call(self, fn):
            return fn(SimpleNamespace(terminal_info=lambda: SimpleNamespace(data_path="")))

    with pytest.raises(MT5Error) as ei:
        capture_chart(
            _NoPath(),
            symbol="EURUSD.z",
            timeframe_name="H1",
            width=800,
            height=600,
            template=None,
            timeout_s=1.0,
            id_factory=lambda: "fixedid",
        )
    assert ei.value.detail.code == "SCREENSHOT_FAILED"
