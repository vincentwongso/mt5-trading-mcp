"""Symbol preparation pipeline."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mt5_mcp.adapter.mt5_client import MT5Client
from mt5_mcp.adapter.symbols import SymbolPrep
from mt5_mcp.errors import MT5Error
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTerminalInfo


@pytest.fixture
def prep(fake_mt5: FakeMT5, frozen_utc) -> SymbolPrep:
    client = MT5Client(mt5_module=fake_mt5)
    client.connect()
    return SymbolPrep(client)


def test_unknown_symbol_raises_not_found(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["XYZ"] = None
    with pytest.raises(MT5Error) as ei:
        prep.get("XYZ")
    assert ei.value.detail.code == "SYMBOL_NOT_FOUND"


def test_hidden_symbol_is_selected(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", visible=False)
    info = prep.get("EURUSD")
    assert info.name == "EURUSD"
    # symbol_select was called exactly once during prep.
    assert fake_mt5.calls.get("symbol_select") == 1


def test_cache_hits_on_second_call(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    prep.get("EURUSD")
    prep.get("EURUSD")
    assert fake_mt5.calls["symbol_info"] == 1


def test_cache_expires(prep: SymbolPrep, fake_mt5: FakeMT5, monkeypatch):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    prep.get("EURUSD")

    # Jump clock forward past TTL.
    import mt5_mcp.adapter.symbols as sym_mod
    t0 = sym_mod._monotonic()
    monkeypatch.setattr(sym_mod, "_monotonic", lambda: t0 + 120)
    prep.get("EURUSD")
    assert fake_mt5.calls["symbol_info"] == 2


def test_validate_volume_ok(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=100.0, volume_step=0.01
    )
    prep.validate_volume("EURUSD", Decimal("0.10"))  # no raise


def test_validate_volume_below_min(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=100.0, volume_step=0.01
    )
    with pytest.raises(MT5Error) as ei:
        prep.validate_volume("EURUSD", Decimal("0.001"))
    assert ei.value.detail.code == "INVALID_VOLUME"
    assert "min" in ei.value.detail.message.lower()


def test_validate_volume_bad_step(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=100.0, volume_step=0.01
    )
    with pytest.raises(MT5Error) as ei:
        prep.validate_volume("EURUSD", Decimal("0.015"))
    assert ei.value.detail.code == "INVALID_VOLUME"


def test_validate_volume_above_max(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", volume_min=0.01, volume_max=10.0, volume_step=0.01
    )
    with pytest.raises(MT5Error):
        prep.validate_volume("EURUSD", Decimal("11"))


def test_quantise_price_rounds_to_digits(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD", digits=5)
    out = prep.quantise_price("EURUSD", Decimal("1.234567"))
    assert out == Decimal("1.23457")


def test_pick_filling_mode_prefers_ioc_for_market(prep: SymbolPrep, fake_mt5: FakeMT5):
    # FOK|IOC available
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=1 | 2
    )
    assert prep.pick_filling_mode("EURUSD", order_type="market") == fake_mt5.ORDER_FILLING_IOC


def test_pick_filling_mode_falls_back_to_fok(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=1  # FOK only
    )
    assert prep.pick_filling_mode("EURUSD", order_type="market") == fake_mt5.ORDER_FILLING_FOK


def test_pick_filling_mode_pending_prefers_return(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=1 | 2 | 4
    )
    assert prep.pick_filling_mode("EURUSD", order_type="limit") == fake_mt5.ORDER_FILLING_RETURN


def test_pick_filling_mode_pending_returns_RETURN_even_without_BOC_bit(prep: SymbolPrep, fake_mt5: FakeMT5):
    # Regression: USOIL/UKOIL on some brokers advertise only IOC bit but pending
    # orders MUST send ORDER_FILLING_RETURN - MT5 rejects pending+IOC with
    # NULL response. The symbol mask is for market orders, not pending.
    fake_mt5._symbol_info["USOIL"] = FakeSymbolInfo(
        name="USOIL", filling_mode=2  # IOC only
    )
    for ot in ("limit", "stop", "stop_limit"):
        assert prep.pick_filling_mode("USOIL", order_type=ot) == fake_mt5.ORDER_FILLING_RETURN


def test_pick_filling_mode_none_matches(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(
        name="EURUSD", filling_mode=0  # broker advertises nothing
    )
    with pytest.raises(MT5Error) as ei:
        prep.pick_filling_mode("EURUSD", order_type="market")
    assert ei.value.detail.code == "INVALID_FILLING_MODE"


def test_invalidate_clears_cache(prep: SymbolPrep, fake_mt5: FakeMT5):
    fake_mt5._symbol_info["EURUSD"] = FakeSymbolInfo(name="EURUSD")
    prep.get("EURUSD")
    prep.invalidate()
    prep.get("EURUSD")
    assert fake_mt5.calls["symbol_info"] == 2
