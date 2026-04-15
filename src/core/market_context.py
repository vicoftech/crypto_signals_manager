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
    def evaluate(df: pd.DataFrame, pair: str, scan_id: str | None = None) -> MarketContext:
        ema21 = float(df["EMA_21"].iloc[-1])
        ema50 = float(df["EMA_50"].iloc[-1])
        close = float(df["close"].iloc[-1])
        ema21_hace3 = float(df["EMA_21"].iloc[-4]) if len(df) >= 4 else ema21

        tendencia_establecida = ema21 > ema50 and close > ema21
        ema21_subiendo = ema21 > ema21_hace3
        reversion_temprana = close > ema50 and ema21_subiendo and close > ema21

        if tendencia_establecida or reversion_temprana:
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
        volume_state = "ACTIVE" if float(df["volume"].iloc[-1]) > vol_avg * 0.9 else "QUIET"

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
        ctx = MarketContext(
            pair=pair,
            trend=trend,
            volatility=volatility,
            volume_state=volume_state,
            atr_viable=atr_viable,
            bb_squeeze=bb_squeeze,
            tradeable=tradeable,
            reason=_build_reason(trend, volatility, volume_state, atr_viable, bb_squeeze),
        )
        if scan_id:
            vol_ratio = (float(df["volume"].iloc[-1]) / vol_avg) if vol_avg else 0.0
            bb_width_s = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]
            bb_w = float(bb_width_s.iloc[-1])
            bb_w_avg = float(bb_width_s.rolling(20).mean().iloc[-1])
            from src.core.audit import log_market_context

            log_market_context(
                scan_id,
                ctx,
                {
                    "ema21": ema21,
                    "ema50": ema50,
                    "close": close,
                    "atr_current": atr_current,
                    "atr_avg": atr_avg,
                    "atr_ratio": ratio,
                    "vol_actual": float(df["volume"].iloc[-1]),
                    "vol_avg": vol_avg,
                    "vol_ratio": vol_ratio,
                    "bb_width": bb_w,
                    "bb_width_avg": bb_w_avg,
                },
            )
        return ctx
