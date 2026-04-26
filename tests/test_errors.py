from mt5_mcp.errors import MT5Error, error_for_retcode
from mt5_mcp.types import ErrorDetail


def test_known_retcode_is_mapped():
    err = error_for_retcode(10019, message="raw")  # NO_MONEY
    assert isinstance(err, ErrorDetail)
    assert err.code == "INSUFFICIENT_MARGIN"
    assert err.requires_human is True
    assert err.mt5_retcode == 10019


def test_unknown_retcode_falls_through():
    err = error_for_retcode(99999, message="raw")
    assert err.code == "MT5_UNKNOWN_RETCODE"
    assert err.details == {"raw_message": "raw"}
    assert err.mt5_retcode == 99999


def test_mt5_error_carries_detail():
    err = MT5Error(ErrorDetail(code="X", message="y", retryable=False, requires_human=False))
    assert err.detail.code == "X"
    assert "X" in str(err)


def test_invalid_approval_error():
    from mt5_mcp.errors import invalid_approval_error

    err = invalid_approval_error(reason="price drift exceeded 0.5%")
    assert err.code == "INVALID_APPROVAL"
    assert err.retryable is True
    assert err.requires_human is True
    assert err.details == {"reason": "price drift exceeded 0.5%"}


def test_exceeds_local_limit_error():
    from decimal import Decimal
    from mt5_mcp.errors import exceeds_local_limit_error

    err = exceeds_local_limit_error(
        limit_name="max_notional_per_trade",
        configured=Decimal("10000"),
        attempted=Decimal("25000"),
    )
    assert err.code == "EXCEEDS_LOCAL_LIMIT"
    assert err.retryable is False
    assert err.requires_human is True
    assert err.details["limit_name"] == "max_notional_per_trade"
    assert err.details["configured"] == "10000"
    assert err.details["attempted"] == "25000"


def test_idempotency_diverged_error():
    from mt5_mcp.errors import idempotency_diverged_error

    err = idempotency_diverged_error(key="01HX...", action="place_order")
    assert err.code == "IDEMPOTENCY_DIVERGED"
    assert err.retryable is False
    assert err.requires_human is True
    assert err.details == {"key": "01HX...", "action": "place_order"}


def test_invalid_ticket_error():
    from mt5_mcp.errors import invalid_ticket_error

    err = invalid_ticket_error(ticket=12345, kind="position")
    assert err.code == "INVALID_TICKET"
    assert err.retryable is False
    assert err.requires_human is False
    assert err.details == {"ticket": 12345, "kind": "position"}


def test_partial_fill_retcode_is_mapped():
    from mt5_mcp.errors import error_for_retcode

    err = error_for_retcode(10010)
    assert err.code == "PARTIAL_FILL"
    assert err.retryable is False
    assert err.requires_human is False
