"""Phase 5 integration tests — drive the server end-to-end against a live MT5 demo terminal.

These tests are marked @pytest.mark.integration and excluded from the default
pytest run. Invoke with `pytest -m integration -v`.

Requirements:
- MT5 terminal installed (Windows or Wine).
- Either: terminal already running and logged in to a demo account, OR
  MT5_LOGIN/MT5_PASSWORD/MT5_SERVER env vars set.
- Demo account has zero open positions and zero pending orders before the run.
"""
