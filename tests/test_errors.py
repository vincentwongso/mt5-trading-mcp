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
