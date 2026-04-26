"""ApprovalStore — in-memory preview cache + retry-validation logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mt5_mcp.policy.consent import ApprovalStore, validate_retry
from mt5_mcp.types import ApprovalPreview, OrderRequest, Quote


def _preview(*, request_id: str, side="buy", volume="0.5",
             ref_bid="1.0823", ref_ask="1.0824",
             symbol="EURUSD", deviation: int = 10,
             expires_in_seconds: int = 300) -> ApprovalPreview:
    now = datetime.now(timezone.utc)
    return ApprovalPreview(
        request_id=request_id,
        expires_at=now + timedelta(seconds=expires_in_seconds),
        summary=f"BUY 0.5 {symbol} @ market (~$54000 USD)",
        action="place_order", symbol=symbol,
        notional=Decimal("54000"), estimated_margin=Decimal("540"),
        reference_quote=Quote(symbol=symbol, bid=Decimal(ref_bid),
                              ask=Decimal(ref_ask), time=now),
        request_echo={"symbol": symbol, "side": side, "type": "market",
                      "volume": volume, "deviation": deviation},
    )


def test_store_and_pop_roundtrip():
    s = ApprovalStore()
    p = _preview(request_id="01HX0000000000000000000001")
    s.put(p)
    out = s.pop("01HX0000000000000000000001")
    assert out is p
    # Preview is consumed on retrieval — single-use.
    assert s.pop("01HX0000000000000000000001") is None


def test_store_evicts_expired_on_pop():
    s = ApprovalStore()
    p = _preview(request_id="01HX0000000000000000000002", expires_in_seconds=-1)
    s.put(p)
    assert s.pop("01HX0000000000000000000002") is None  # expired → treated as missing


def test_validate_retry_accepts_matching_request():
    p = _preview(request_id="01HX0000000000000000000003")
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=10,
                       approval_confirmed=True, approval_request_id=p.request_id)
    point = Decimal("0.00001")
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"), point=point)
    assert err is None


def test_validate_retry_rejects_volume_mismatch():
    p = _preview(request_id="01HX0000000000000000000004", volume="0.5")
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("1.0"), approval_confirmed=True,
                       approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "volume" in err.details["reason"].lower()


def test_validate_retry_rejects_price_drift_beyond_tolerance():
    p = _preview(request_id="01HX0000000000000000000005")
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=10,
                       approval_confirmed=True, approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.10"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "price" in err.details["reason"].lower()


def test_validate_retry_allows_drift_within_deviation_when_pct_tighter():
    # ref_ask = 0.5; 0.5% of 0.5 = 0.0025; deviation=100 points × point=0.001 → 0.1.
    # Tolerance = max(0.0025, 0.1) = 0.1. Drift 0.05 is within.
    p = _preview(request_id="01HX0000000000000000000006",
                 symbol="X", deviation=100,
                 ref_bid="0.499", ref_ask="0.500")
    req = OrderRequest(symbol="X", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=100,
                       approval_confirmed=True, approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("0.55"),
                         point=Decimal("0.001"))
    assert err is None  # 100 points × 0.001 = 0.1 tolerance dominates


def test_validate_retry_rejects_expired_preview():
    p = _preview(request_id="01HX0000000000000000000007", expires_in_seconds=-1)
    req = OrderRequest(symbol="EURUSD", side="buy", type="market",
                       volume=Decimal("0.5"), approval_confirmed=True,
                       approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "expired" in err.details["reason"].lower()


def test_validate_retry_rejects_symbol_mismatch():
    """Approval for one symbol must not be honoured for another.

    Regression guard: an earlier implementation removed `symbol` from the
    identical-fields loop, allowing an agent to receive approval for
    EURUSD and submit GBPUSD — exactly the bait-and-switch the consent
    gate is supposed to prevent.
    """
    p = _preview(request_id="01HX0000000000000000000099", symbol="EURUSD")
    req = OrderRequest(symbol="GBPUSD", side="buy", type="market",
                       volume=Decimal("0.5"), deviation=10,
                       approval_confirmed=True, approval_request_id=p.request_id)
    err = validate_retry(req, preview=p, current_price=Decimal("1.0824"),
                         point=Decimal("0.00001"))
    assert err is not None
    assert err.code == "INVALID_APPROVAL"
    assert "symbol" in err.details["reason"].lower()


def test_new_request_id_format():
    from mt5_mcp.policy.consent import new_request_id

    rid = new_request_id()
    assert isinstance(rid, str)
    assert len(rid) == 26  # canonical ULID length
