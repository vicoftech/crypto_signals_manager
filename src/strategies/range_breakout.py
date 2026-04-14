from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, Opportunity, simple_long_opportunity


class RangeBreakoutStrategy(BaseStrategy):
    name = "RangeBreakout"
    timeframes = ["15m", "1h"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        resistance = float(df["high"].tail(10).max())
        conds = [("breaks_resistance", float(df["close"].iloc[-1]) >= resistance)]
        return simple_long_opportunity(pair, self.name, "15m", df, ctx, 10) if self._check_conditions(conds) else None
