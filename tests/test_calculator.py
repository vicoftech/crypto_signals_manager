from __future__ import annotations

from src.core.calculator import with_risk
from src.core.market_context import MarketContext
from src.strategies.base import Opportunity


def test_calculator_builds_rr():
    op = Opportunity(
        pair="BTCUSDT",
        strategy="EMAPullback",
        timeframe="30m",
        direction="LONG",
        entry_price=100.0,
        sl_price=99.0,
        tp1_price=101.5,
        tp2_price=103.0,
        sl_type="low",
        market_context=MarketContext("BTCUSDT", "BULLISH", "MEDIUM", "ACTIVE", True, False, True, "ok"),
    )
    out = with_risk(op, 100.0)
    assert out["rr_ratio"] >= 3.0
