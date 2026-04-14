from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, Opportunity, simple_long_opportunity


class EMAPullbackStrategy(BaseStrategy):
    name = "EMAPullback"
    timeframes = ["15m", "30m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        conds = [
            ("ema_up", float(df["EMA_21"].iloc[-1]) > float(df["EMA_50"].iloc[-1])),
            ("price_above_ema21", float(df["close"].iloc[-1]) > float(df["EMA_21"].iloc[-1])),
        ]
        return simple_long_opportunity(pair, self.name, "30m", df, ctx, 3) if self._check_conditions(conds) else None
