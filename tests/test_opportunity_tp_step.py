from __future__ import annotations

from src.core.market_context import MarketContext
from src.core.tp_ladder import tp_price_for_level
from src.strategies.base import simple_long_opportunity
import pandas as pd


def _ctx():
    return MarketContext("BTCUSDT", "BULLISH", "MEDIUM", "ACTIVE", True, False, True, "ok")


def test_opportunity_uses_settings_tp_step():
    # Build minimal df with close=100, low lookback min=99
    n = 30
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
        }
    )
    df.loc[df.index[-1], "close"] = 100.0
    df.loc[df.index[-3:], "low"] = 99.0
    opp = simple_long_opportunity("BTCUSDT", "Test", "30m", df, _ctx(), sl_lookback=3)
    assert opp is not None
    assert abs(opp.tp1_price - tp_price_for_level(100.0, 99.0, 1)) < 1e-9
    assert abs(opp.tp2_price - tp_price_for_level(100.0, 99.0, 2)) < 1e-9
    assert abs(opp.tp3_price - tp_price_for_level(100.0, 99.0, 3)) < 1e-9
    assert abs(opp.tp1_price - 101.0) < 1e-9
