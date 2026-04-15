from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, simple_long_opportunity


class MACDCrossStrategy(BaseStrategy):
    name = "MACDCross"
    timeframes = ["30m", "1h"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext):
        if not ctx.tradeable:
            return None

        macd = df["MACD_12_26_9"]
        signal = df["MACDs_12_26_9"]
        hist = df["MACDh_12_26_9"]
        close = float(df["close"].iloc[-1])

        macd_actual = float(macd.iloc[-1])
        signal_actual = float(signal.iloc[-1])
        macd_anterior = float(macd.iloc[-2])
        signal_anterior = float(signal.iloc[-2])

        fue_cruce = macd_anterior <= signal_anterior and macd_actual > signal_actual
        if not fue_cruce:
            return None

        umbral_zona_cero = close * 0.001

        cruce_bajo_cero = macd_actual < 0
        cruce_zona_cero = abs(macd_actual) <= umbral_zona_cero
        histograma_actual = float(hist.iloc[-1])
        histograma_anterior = float(hist.iloc[-2])
        cruce_acelerando = macd_actual > 0 and histograma_actual > histograma_anterior > 0

        if not (cruce_bajo_cero or cruce_zona_cero or cruce_acelerando):
            return None

        if float(df["EMA_50"].iloc[-1]) < float(df["EMA_50"].iloc[-5]):
            return None

        return simple_long_opportunity(pair, self.name, "30m", df, ctx, sl_lookback=5)
