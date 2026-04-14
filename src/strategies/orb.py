from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, Opportunity, simple_long_opportunity


class ORBStrategy(BaseStrategy):
    name = "ORB"
    timeframes = ["15m"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        opening_high = float(df["high"].head(4).max())
        conds = [("opening_breakout", float(df["close"].iloc[-1]) > opening_high)]
        return simple_long_opportunity(pair, self.name, "15m", df, ctx, 4) if self._check_conditions(conds) else None
