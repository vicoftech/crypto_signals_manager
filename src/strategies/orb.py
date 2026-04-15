from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, simple_long_opportunity


class ORBStrategy(BaseStrategy):
    name = "ORB"
    timeframes = ["15m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext):
        if not ctx.tradeable:
            return None
        if "timestamp" not in df.columns:
            return None

        now = pd.Timestamp.now(tz="UTC")
        if now.hour >= 6:
            return None

        hoy_utc = now.normalize()
        ts = pd.to_datetime(df["timestamp"], utc=True)
        df_hoy = df.loc[ts >= hoy_utc].copy()

        if len(df_hoy) < 4:
            return None

        rango_apertura = df_hoy.head(4)
        opening_high = float(rango_apertura["high"].max())
        opening_low = float(rango_apertura["low"].min())

        close_actual = float(df["close"].iloc[-1])
        if close_actual <= opening_high:
            return None

        vol_actual = float(df["volume"].iloc[-1])
        vol_avg_20 = float(df["volume"].rolling(20).mean().iloc[-1])
        if vol_actual < vol_avg_20 * 1.3:
            return None

        return simple_long_opportunity(
            pair, self.name, "15m", df, ctx, sl_lookback=4, sl_override=opening_low
        )
