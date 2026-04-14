from __future__ import annotations

import pandas as pd

from src.core.market_context import MarketContext
from src.strategies.base import BaseStrategy, Opportunity, simple_long_opportunity


class MACDCrossStrategy(BaseStrategy):
    name = "MACDCross"
    timeframes = ["30m", "1h"]

    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        macd = float(df["MACD_12_26_9"].iloc[-1])
        signal = float(df["MACDs_12_26_9"].iloc[-1])
        conds = [("bullish_cross", macd > signal), ("below_zero", macd < 0)]
        return simple_long_opportunity(pair, self.name, "30m", df, ctx, 5) if self._check_conditions(conds) else None
