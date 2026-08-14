from __future__ import annotations

from src.core.calculator import with_risk
from src.core.market_context import MarketContext
from src.strategies.base import Opportunity


def _op(sl: float = 99.0) -> Opportunity:
    return Opportunity(
        pair="BTCUSDT",
        strategy="EMAPullback",
        timeframe="30m",
        direction="LONG",
        entry_price=100.0,
        sl_price=sl,
        tp1_price=101.0,
        tp2_price=102.0,
        tp3_price=103.0,
        sl_type="low",
        market_context=MarketContext(
            "BTCUSDT", "BULLISH", "MEDIUM", "ACTIVE", True, False, True, "ok"
        ),
    )


def test_calculator_builds_rr():
    out = with_risk(_op(), 100.0)
    assert out["rr_ratio"] >= 3.0


def test_fixed_sl_one_percent_and_tps():
    # Strategy SL was 98 (2%); with_risk must force 1% and TPs at 1/2/3R.
    out = with_risk(_op(sl=98.0), 100.0)
    assert abs(out["sl_pct"] - 0.01) < 1e-9
    assert abs(out["sl_price"] - 99.0) < 1e-9
    assert abs(out["tp1_price"] - 101.0) < 1e-6
    assert abs(out["tp2_price"] - 102.0) < 1e-6
    assert abs(out["tp3_price"] - 103.0) < 1e-6
    assert abs(out["rr_ratio"] - 3.0) < 1e-6


def test_position_is_five_percent_of_free_usdt(monkeypatch):
    # Sizing desde capital_disponible del snapshot (USDT libre testnet).
    class Snap:
        def as_dict(self):
            return {
                "capital_disponible": 1100.0,
                "capital_bloqueado": 0.0,
                "capital_context": "live_usdt",
            }

    monkeypatch.setattr("src.core.calculator.get_capital_snapshot", lambda: Snap())
    monkeypatch.setattr(
        "src.core.calculator.ConfigStore.get_risk_pct",
        lambda self, default=0.05: 0.05,
    )
    monkeypatch.setattr(
        "src.core.calculator._sizing_capital_disponible",
        lambda snap: float(snap["capital_disponible"]),
    )
    out = with_risk(_op(), 100.0)
    assert abs(out["position_size_usd"] - 55.0) < 1e-6
    assert abs(out["risk_usd"] - 0.55) < 1e-6
