from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.config import settings


@dataclass
class MarketContext:
    pair: str
    trend: str
    volatility: str
    volume_state: str
    atr_viable: bool
    bb_squeeze: bool
    tradeable: bool
    reason: str


def _build_reason(
    trend: str, volatility: str, volume_state: str, atr_viable: bool, bb_squeeze: bool
) -> str:
    parts = [
        f"trend={trend}",
        f"volatility={volatility}",
        f"volume={volume_state}",
        f"atr_viable={atr_viable}",
        f"bb_squeeze={bb_squeeze}",
    ]
    return " | ".join(parts)


class MarketContextEvaluator:
    @staticmethod
    def evaluate(df: pd.DataFrame, pair: str) -> MarketContext:
        ema21 = float(df["EMA_21"].iloc[-1])
        ema50 = float(df["EMA_50"].iloc[-1])
        close = float(df["close"].iloc[-1])
        if ema21 > ema50 and close > ema21:
            trend = "BULLISH"
        elif ema21 < ema50 and close < ema21:
            trend = "BEARISH"
        else:
            trend = "SIDEWAYS"

        atr_current = float(df["ATRr_14"].iloc[-1])
        atr_avg = float(df["ATRr_14"].rolling(20).mean().iloc[-1])
        ratio = atr_current / atr_avg if atr_avg else 0.0
        volatility = "HIGH" if ratio > 1.3 else "MEDIUM" if ratio > 0.7 else "LOW"

        vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
        volume_state = "ACTIVE" if float(df["volume"].iloc[-1]) > vol_avg * 1.1 else "QUIET"

        atr_viable = (atr_current * 0.5) <= settings.max_sl_pct
        bb_width = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]
        bb_squeeze = bool(bb_width.iloc[-1] < (bb_width.rolling(20).mean().iloc[-1] * 0.7))

        tradeable = (
            trend == "BULLISH"
            and volatility in ("MEDIUM", "HIGH")
            and volume_state == "ACTIVE"
            and atr_viable
            and not bb_squeeze
        )
        return MarketContext(
            pair=pair,
            trend=trend,
            volatility=volatility,
            volume_state=volume_state,
            atr_viable=atr_viable,
            bb_squeeze=bb_squeeze,
            tradeable=tradeable,
            reason=_build_reason(trend, volatility, volume_state, atr_viable, bb_squeeze),
        )
