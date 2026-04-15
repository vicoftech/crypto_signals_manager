from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, simple_long_opportunity


class RangeBreakoutStrategy(BaseStrategy):
    name = "RangeBreakout"
    timeframes = ["15m", "1h"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext):
        if not ctx.tradeable:
            return None

        atr_rango = float(df["ATRr_14"].iloc[-11:-1].mean())
        atr_total = float(df["ATRr_14"].rolling(20).mean().iloc[-1])
        if atr_rango > atr_total * 0.9:
            return None

        resistencia = float(df["high"].iloc[-11:-1].max())
        close_actual = float(df["close"].iloc[-1])
        if close_actual < resistencia:
            return None

        vol_actual = float(df["volume"].iloc[-1])
        vol_avg_20 = float(df["volume"].rolling(20).mean().iloc[-1])
        if vol_actual < vol_avg_20 * 1.3:
            return None

        vela = df.iloc[-1]
        mitad_rango = (float(vela["high"]) + float(vela["low"])) / 2
        if float(vela["close"]) < mitad_rango:
            return None

        return simple_long_opportunity(pair, self.name, "15m", df, ctx, sl_lookback=10)
