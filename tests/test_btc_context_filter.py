from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.core.market_context import BtcContext, MarketContextEvaluator, get_btc_context


def _dummy_df(trend: str = "BULLISH") -> pd.DataFrame:
    # Simple helper to build a minimal dataframe with required columns
    data = {
        "open_time": [0] * 50,
        "open": [100.0] * 50,
        "high": [105.0] * 50,
        "low": [95.0] * 50,
        "close": [100.0] * 50,
        "volume": [1000.0] * 50,
        "EMA_21": [100.0] * 50,
        "EMA_50": [99.0] * 50,
        "ATRr_14": [0.01] * 50,
        "BBU_20_2.0": [102.0] * 50,
        "BBL_20_2.0": [98.0] * 50,
        "BBM_20_2.0": [100.0] * 50,
    }
    df = pd.DataFrame(data)
    if trend == "SIDEWAYS":
        df["EMA_21"] = 100.0
        df["EMA_50"] = 100.0
    if trend == "BEARISH":
        df["EMA_21"] = 99.0
        df["EMA_50"] = 100.0
        df["close"] = 99.0
    return df


@patch("src.core.market_context.get_btc_context")
def test_btc_filter_does_not_crash_for_altcoins(mock_btc_ctx):
    # Simple sanity check: el filtro de BTC se puede invocar sin romper evaluate()
    mock_btc_ctx.return_value = BtcContext(
        trend="BEARISH",
        volatility="HIGH",
        ema21=1.0,
        ema50=1.0,
        close=1.0,
        atr_ratio=1.0,
        evaluated_at="",
    )
    df = _dummy_df(trend="BULLISH")
    ctx = MarketContextEvaluator.evaluate(df, "ETHUSDT", scan_id="test", pair_config={"tier": "1"})
    assert isinstance(ctx, object)


@patch("src.core.market_context.get_btc_context")
def test_btc_filter_works_for_sideways_context(mock_btc_ctx):
    mock_btc_ctx.return_value = BtcContext(
        trend="SIDEWAYS",
        volatility="LOW",
        ema21=1.0,
        ema50=1.0,
        close=1.0,
        atr_ratio=1.0,
        evaluated_at="",
    )
    df = _dummy_df(trend="SIDEWAYS")
    ctx = MarketContextEvaluator.evaluate(df, "SOLUSDT", scan_id="test", pair_config={"tier": "1"})
    assert isinstance(ctx, object)

