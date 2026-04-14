from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, Opportunity, simple_long_opportunity


class SupportBounceStrategy(BaseStrategy):
    name = "SupportBounce"
    timeframes = ["15m", "30m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        support = float(df["low"].tail(50).nsmallest(2).mean())
        close = float(df["close"].iloc[-1])
        conds = [("near_support", close <= support * 1.003)]
        return simple_long_opportunity(pair, self.name, "30m", df, ctx, 5) if self._check_conditions(conds) else None
