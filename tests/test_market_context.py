from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContextEvaluator


def test_market_context_evaluate_returns_object():
    base = {
        "close": [100 + i for i in range(30)],
        "volume": [1000] * 30,
        "EMA_21": [100 + i * 0.8 for i in range(30)],
        "EMA_50": [95 + i * 0.6 for i in range(30)],
        "ATRr_14": [0.01] * 30,
        "BBU_20_2.0": [102] * 30,
        "BBL_20_2.0": [98] * 30,
        "BBM_20_2.0": [100] * 30,
    }
    df = pd.DataFrame(base)
    ctx = MarketContextEvaluator.evaluate(df, "BTCUSDT")
    assert ctx.pair == "BTCUSDT"
    assert ctx.trend in {"BULLISH", "BEARISH", "SIDEWAYS"}
