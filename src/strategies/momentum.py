from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, simple_long_opportunity


class MomentumContinuationStrategy(BaseStrategy):
    name = "Momentum"
    timeframes = ["15m", "30m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext):
        if not ctx.tradeable:
            return None

        for i in (-3, -2, -1):
            vela = df.iloc[i]
            cuerpo = abs(float(vela["close"]) - float(vela["open"]))
            rango = float(vela["high"]) - float(vela["low"]) + 1e-10
            es_alcista = float(vela["close"]) > float(vela["open"])
            cuerpo_solido = (cuerpo / rango) >= 0.4
            if not es_alcista or not cuerpo_solido:
                return None

        precio_inicio = float(df["open"].iloc[-3])
        precio_fin = float(df["close"].iloc[-1])
        magnitud_impulso = (precio_fin - precio_inicio) / precio_inicio
        if magnitud_impulso < 0.005:
            return None

        rsi = float(df["RSI_14"].iloc[-1])
        if not (50 <= rsi <= 70):
            return None

        vol_1 = float(df["volume"].iloc[-3])
        vol_2 = float(df["volume"].iloc[-2])
        vol_3 = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
        if not (vol_3 >= vol_2 >= vol_1):
            if vol_3 < vol_avg * 1.0:
                return None

        return simple_long_opportunity(pair, self.name, "15m", df, ctx, sl_lookback=3)
