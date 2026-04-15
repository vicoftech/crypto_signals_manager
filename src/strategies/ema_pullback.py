from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, simple_long_opportunity


class EMAPullbackStrategy(BaseStrategy):
    name = "EMAPullback"
    timeframes = ["15m", "30m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext):
        if not ctx.tradeable:
            return None

        ema21 = df["EMA_21"]
        ema50 = df["EMA_50"]
        close = df["close"]
        open_ = df["open"]

        if not (float(ema21.iloc[-1]) > float(ema50.iloc[-1])):
            return None

        toco_ema = False
        for i in (-3, -2, -1):
            low_vela = float(df["low"].iloc[i])
            ema_vela = float(ema21.iloc[i])
            if low_vela <= ema_vela * 1.001:
                toco_ema = True
                break

        if not toco_ema:
            return None

        if float(close.iloc[-1]) <= float(ema21.iloc[-1]):
            return None

        if float(close.iloc[-1]) <= float(open_.iloc[-1]):
            return None

        vela = df.iloc[-1]
        cuerpo = abs(float(vela["close"]) - float(vela["open"]))
        rango = float(vela["high"]) - float(vela["low"]) + 1e-10
        if cuerpo / rango < 0.4:
            return None

        return simple_long_opportunity(pair, self.name, "30m", df, ctx, sl_lookback=3)
