from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

import pandas as pd

from src.core.market_context import MarketContext

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    pair: str
    strategy: str
    timeframe: str
    direction: str
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    sl_type: str
    market_context: MarketContext
    confluence: bool = False
    timestamp: datetime = datetime.now(tz=timezone.utc)


class BaseStrategy(ABC):
    name: str
    timeframes: list[str]

    @abstractmethod
    def analyze(self, df: pd.DataFrame, pair: str, ctx: MarketContext) -> Opportunity | None:
        raise NotImplementedError

    def _check_conditions(self, conditions: list[tuple[str, bool]]) -> bool:
        for cond_name, result in conditions:
            if not result:
                logger.debug("[%s] Fallo: %s", self.name, cond_name)
                return False
        return True


def simple_long_opportunity(
    pair: str, strategy: str, timeframe: str, df: pd.DataFrame, ctx: MarketContext, sl_lookback: int = 3
) -> Opportunity | None:
    if not ctx.tradeable:
        return None
    entry = float(df["close"].iloc[-1])
    sl = float(df["low"].tail(sl_lookback).min())
    risk = entry - sl
    if risk <= 0:
        return None
    return Opportunity(
        pair=pair,
        strategy=strategy,
        timeframe=timeframe,
        direction="LONG",
        entry_price=entry,
        sl_price=sl,
        tp1_price=entry + (risk * 1.5),
        tp2_price=entry + (risk * 3.0),
        sl_type=f"low_{sl_lookback}_candles",
        market_context=ctx,
    )
