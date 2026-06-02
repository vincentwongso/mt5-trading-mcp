"""End-to-end coverage for the PolicyEngine context manager."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mt5_mcp.config import Config, PolicySection
from mt5_mcp.policy import PolicyEngine, PreflightInputs
from mt5_mcp.types import (
    ApprovalPreview, OrderRequest, OrderResult, Quote,
)
from tests.fakes import FakeOrderSendResult, TRADE_RETCODE_DONE


def _config(*, auto_approve="1000", max_notional="100000") -> Config:
    return Config(policy=PolicySection(
        auto_approve_notional=Decimal(auto_approve),
        max_notional_per_trade=Decimal(max_notional),
    ))


@pytest.fixture
def engine(tmp_path: Path) -> PolicyEngine:
    cfg = _config()
    e = PolicyEngine(
        config=cfg,
        idempotency_path=tmp_path / "idem.db",
        audit_path=tmp_path / "audit.jsonl",
    )
    yield e
    e.close()


def _raw_done(*, order: int, price: float = 1.0824) -> FakeOrderSendResult:
    return FakeOrderSendResult(retcode=TRADE_RETCODE_DONE, order=order,
                               volume=0.1, price=price)


def _raw_to_result(raw, *, action="place_order", symbol="EURUSD",
                   request_volume=Decimal("0.1"), request_echo=None) -> OrderResult:
    return OrderResult(
        success=raw.retcode == TRADE_RETCODE_DONE,
        ticket=raw.order if raw.order else None,
        action=action, symbol=symbol, volume=request_volume,
        price_filled=Decimal(str(raw.price)) if raw.price else None,
        request_echo=request_echo or {},
        replayed=False,
        error=None,
        server_response_code=raw.retcode,
    )


def test_under_threshold_executes_directly(engine: PolicyEngine, tmp_path):
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.1"))
    inputs = PreflightInputs(notional=Decimal("100"))
    with engine.guard("place_order", req,
                      requires_approval=False, preflight_inputs=inputs) as g:
        assert g.short_circuit is None
        raw = g.execute(lambda: _raw_done(order=42))
        out = g.finalize(_raw_to_result, request_echo={"symbol": "EURUSD"})

    assert out["success"] is True
    assert out["ticket"] == 42

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["action"] == "executed"
    assert rec["tool"] == "place_order"


def test_requires_approval_short_circuits_with_preview(engine: PolicyEngine, tmp_path):
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"))
    inputs = PreflightInputs(notional=Decimal("54000"))
    preview = ApprovalPreview(
        request_id="will-be-overwritten",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        summary="x", action="place_order", symbol="EURUSD",
        notional=Decimal("54000"), estimated_margin=Decimal("540"),
        reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                              ask=Decimal("1.0824"),
                              time=datetime.now(timezone.utc)),
        request_echo={"symbol": "EURUSD", "side": "buy", "volume": "0.5",
                      "type": "market", "deviation": 10},
    )

    with engine.guard("place_order", req,
                      requires_approval=True,
                      preview_factory=lambda: preview,
                      preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        out = g.short_circuit

    assert out["request_id"] != "will-be-overwritten"
    assert len(out["request_id"]) == 26

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["action"] == "requires_approval"


def test_approval_confirmed_executes_when_retry_matches(tmp_path: Path):
    cfg = _config()
    e = PolicyEngine(config=cfg, idempotency_path=tmp_path / "idem.db",
                     audit_path=tmp_path / "audit.jsonl")
    try:
        req1 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("0.5"), deviation=10)
        preview = ApprovalPreview(
            request_id="x",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            summary="x", action="place_order", symbol="EURUSD",
            notional=Decimal("54000"), estimated_margin=Decimal("540"),
            reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                                  ask=Decimal("1.0824"),
                                  time=datetime.now(timezone.utc)),
            request_echo={"symbol": "EURUSD", "side": "buy", "volume": "0.5",
                          "type": "market", "deviation": 10},
        )
        with e.guard("place_order", req1,
                     requires_approval=True,
                     preview_factory=lambda: preview,
                     preflight_inputs=PreflightInputs(notional=Decimal("54000"))) as g:
            request_id = g.short_circuit["request_id"]

        req2 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("0.5"), deviation=10,
                            approval_confirmed=True,
                            approval_request_id=request_id)
        with e.guard("place_order", req2,
                     requires_approval=True,
                     current_price=Decimal("1.0824"),
                     symbol_point=Decimal("0.00001"),
                     preflight_inputs=PreflightInputs(notional=Decimal("54000"))) as g:
            assert g.short_circuit is None
            raw = g.execute(lambda: _raw_done(order=99))
            out = g.finalize(_raw_to_result, request_echo={"symbol": "EURUSD"})
        assert out["success"] is True and out["ticket"] == 99
    finally:
        e.close()


def test_approval_invalid_when_volume_changes_between_calls(tmp_path: Path):
    cfg = _config()
    e = PolicyEngine(config=cfg, idempotency_path=tmp_path / "idem.db",
                     audit_path=tmp_path / "audit.jsonl")
    try:
        req1 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("0.5"))
        preview = ApprovalPreview(
            request_id="x",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            summary="x", action="place_order", symbol="EURUSD",
            notional=Decimal("54000"), estimated_margin=Decimal("540"),
            reference_quote=Quote(symbol="EURUSD", bid=Decimal("1.0823"),
                                  ask=Decimal("1.0824"),
                                  time=datetime.now(timezone.utc)),
            request_echo={"symbol": "EURUSD", "side": "buy", "volume": "0.5",
                          "type": "market", "deviation": 10},
        )
        with e.guard("place_order", req1, requires_approval=True,
                     preview_factory=lambda: preview,
                     preflight_inputs=PreflightInputs(notional=Decimal("54000"))) as g:
            request_id = g.short_circuit["request_id"]

        req2 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                            volume=Decimal("1.0"),
                            approval_confirmed=True, approval_request_id=request_id)
        with e.guard("place_order", req2, requires_approval=True,
                     current_price=Decimal("1.0824"),
                     symbol_point=Decimal("0.00001"),
                     preflight_inputs=PreflightInputs(notional=Decimal("108000"))) as g:
            assert g.short_circuit is not None
            assert g.short_circuit["error"]["code"] == "INVALID_APPROVAL"
    finally:
        e.close()


def test_preflight_refusal_short_circuits(engine: PolicyEngine, tmp_path):
    e = engine
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("100"))
    inputs = PreflightInputs(notional=Decimal("999999"))
    e._config = _config(max_notional="1000")
    with e.guard("place_order", req, requires_approval=False,
                 preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        assert g.short_circuit["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"

    last = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert last["action"] == "preflight_refused"


def test_idempotency_replay_returns_cached_with_replayed_flag(engine: PolicyEngine):
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.1"), idempotency_key="k1")
    inputs = PreflightInputs(notional=Decimal("100"))
    with engine.guard("place_order", req, requires_approval=False,
                      preflight_inputs=inputs) as g:
        g.execute(lambda: _raw_done(order=77))
        first = g.finalize(_raw_to_result, request_echo={"x": 1})
    assert first["replayed"] is False

    with engine.guard("place_order", req, requires_approval=False,
                      preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        assert g.short_circuit["replayed"] is True
        assert g.short_circuit["ticket"] == 77


def test_velocity_cap_blocks_place_orders_beyond_limit(tmp_path: Path):
    """max_orders_per_minute throttles place_order: with cap=2, the first two
    executions in a 60s window succeed and the third is refused with
    EXCEEDS_LOCAL_LIMIT; once the window clears, orders are allowed again."""
    cfg = Config(policy=PolicySection(
        auto_approve_notional=Decimal("100000"),  # don't gate; isolate velocity
        max_notional_per_trade=Decimal("100000"),
        max_orders_per_minute=2,
    ))
    clock = [1000.0]  # injected monotonic clock
    e = PolicyEngine(config=cfg, idempotency_path=tmp_path / "idem.db",
                     audit_path=tmp_path / "audit.jsonl", clock=lambda: clock[0])

    def place(order: int):
        req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                           volume=Decimal("0.1"))
        with e.guard("place_order", req, requires_approval=False,
                     preflight_inputs=PreflightInputs(notional=Decimal("100"))) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            g.execute(lambda: _raw_done(order=order))
            return g.finalize(_raw_to_result, request_echo={"x": 1})

    try:
        assert place(1)["success"] is True
        assert place(2)["success"] is True
        blocked = place(3)
        assert "error" in blocked
        assert blocked["error"]["code"] == "EXCEEDS_LOCAL_LIMIT"
        assert blocked["error"]["details"]["limit_name"] == "max_orders_per_minute"
        # Advance past the 60s window → the cap resets.
        clock[0] += 61.0
        assert place(4)["success"] is True
    finally:
        e.close()


def test_idempotency_diverged_when_same_key_different_request(engine: PolicyEngine):
    req1 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                        volume=Decimal("0.1"), idempotency_key="k2")
    req2 = OrderRequest(symbol="EURUSD", side="buy", type="market",
                        volume=Decimal("0.5"),
                        idempotency_key="k2")
    inputs = PreflightInputs(notional=Decimal("100"))
    with engine.guard("place_order", req1, requires_approval=False,
                      preflight_inputs=inputs) as g:
        g.execute(lambda: _raw_done(order=88))
        g.finalize(_raw_to_result, request_echo={"x": 1})

    with engine.guard("place_order", req2, requires_approval=False,
                      preflight_inputs=inputs) as g:
        assert g.short_circuit is not None
        assert g.short_circuit["error"]["code"] == "IDEMPOTENCY_DIVERGED"
