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


def _ctx_df(
    *,
    ema21_last: float,
    ema50_last: float,
    close_last: float,
    ema21_prev3: float | None = None,
    volume_last: float = 1000.0,
    vol_avg_factor: float = 1.0,
    atr_last: float = 0.01,
) -> pd.DataFrame:
    n = 30
    ema21 = [100.0] * n
    ema50 = [95.0] * n
    close = [100.0 + i * 0.5 for i in range(n)]
    ema21[-1] = ema21_last
    ema50[-1] = ema50_last
    close[-1] = close_last
    if ema21_prev3 is not None and len(ema21) >= 4:
        ema21[-4] = ema21_prev3
    vol = [1000.0 * vol_avg_factor] * n
    vol[-1] = volume_last
    return pd.DataFrame(
        {
            "close": close,
            "volume": vol,
            "EMA_21": ema21,
            "EMA_50": ema50,
            "ATRr_14": [atr_last] * n,
            "BBU_20_2.0": [102] * n,
            "BBL_20_2.0": [98] * n,
            "BBM_20_2.0": [100] * n,
        }
    )


def test_contexto_tendencia_establecida():
    df = _ctx_df(ema21_last=110.0, ema50_last=100.0, close_last=115.0)
    ctx = MarketContextEvaluator.evaluate(df, "BTCUSDT")
    assert ctx.trend == "BULLISH"


def test_contexto_reversion_temprana():
    df = _ctx_df(
        ema21_last=102.0,
        ema50_last=104.0,
        close_last=105.0,
        ema21_prev3=100.0,
    )
    ctx = MarketContextEvaluator.evaluate(df, "BTCUSDT")
    assert ctx.trend == "BULLISH"


def test_contexto_reversion_temprana_ema21_plana():
    df = _ctx_df(
        ema21_last=102.0,
        ema50_last=104.0,
        close_last=105.0,
        ema21_prev3=102.0,
    )
    ctx = MarketContextEvaluator.evaluate(df, "BTCUSDT")
    assert ctx.trend == "SIDEWAYS"


def test_contexto_volumen_moderado_activo():
    df = _ctx_df(ema21_last=110.0, ema50_last=100.0, close_last=115.0, volume_last=950.0, vol_avg_factor=1.0)
    ctx = MarketContextEvaluator.evaluate(df, "BTCUSDT")
    assert ctx.volume_state == "ACTIVE"


def test_contexto_volumen_muy_bajo_quiet():
    df = _ctx_df(ema21_last=110.0, ema50_last=100.0, close_last=115.0, volume_last=800.0, vol_avg_factor=1.0)
    ctx = MarketContextEvaluator.evaluate(df, "BTCUSDT")
    assert ctx.volume_state == "QUIET"
