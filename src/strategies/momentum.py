from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, Opportunity, simple_long_opportunity


class MomentumContinuationStrategy(BaseStrategy):
    name = "Momentum"
    timeframes = ["15m", "30m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        c1 = float(df["close"].iloc[-1]) > float(df["open"].iloc[-1])
        c2 = float(df["close"].iloc[-2]) > float(df["open"].iloc[-2])
        c3 = float(df["close"].iloc[-3]) > float(df["open"].iloc[-3])
        conds = [("three_green_candles", all([c1, c2, c3]))]
        return simple_long_opportunity(pair, self.name, "15m", df, ctx, 3) if self._check_conditions(conds) else None
