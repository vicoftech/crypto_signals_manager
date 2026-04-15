from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, simple_long_opportunity


class SupportBounceStrategy(BaseStrategy):
    name = "SupportBounce"
    timeframes = ["15m", "30m"]

    @staticmethod
    def _calcular_soporte(lows: pd.Series) -> float | None:
        if len(lows) < 10:
            return None

        sorted_lows = lows.sort_values().values
        clusters: list[list[float]] = []
        cluster_actual: list[float] = [float(sorted_lows[0])]

        for low in sorted_lows[1:]:
            low = float(low)
            if (low - cluster_actual[0]) / cluster_actual[0] <= 0.005:
                cluster_actual.append(low)
            else:
                if len(cluster_actual) >= 2:
                    clusters.append(cluster_actual)
                cluster_actual = [low]

        if len(cluster_actual) >= 2:
            clusters.append(cluster_actual)

        if not clusters:
            return None

        mejor_cluster = max(clusters, key=len)
        return sum(mejor_cluster) / len(mejor_cluster)

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext):
        if not ctx.tradeable:
            return None

        lows_50 = df["low"].iloc[-50:]
        support = self._calcular_soporte(lows_50)
        if support is None:
            return None

        margen_toque = support * 1.003
        toco_soporte = float(df["low"].iloc[-3:].min()) <= margen_toque
        if not toco_soporte:
            return None

        close_actual = float(df["close"].iloc[-1])
        if close_actual <= support:
            return None

        rsi = float(df["RSI_14"].iloc[-1])
        if rsi >= 40:
            return None

        vela = df.iloc[-1]
        cuerpo_min = min(float(vela["open"]), float(vela["close"]))
        rango_total = float(vela["high"]) - float(vela["low"]) + 1e-10
        mecha_inferior = (cuerpo_min - float(vela["low"])) / rango_total
        if mecha_inferior < 0.35:
            return None

        sl_price = support * 0.998
        return simple_long_opportunity(
            pair, self.name, "30m", df, ctx, sl_lookback=5, sl_override=sl_price
        )
