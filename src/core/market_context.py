from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging

import pandas as pd

from src.config import settings
from src.core.binance_client import BinanceClient
from src.core.indicators import enrich_dataframe

logger = logging.getLogger(__name__)


@dataclass
class BtcContext:
    trend: str          # "BULLISH" | "BEARISH" | "SIDEWAYS"
    volatility: str     # "HIGH" | "MEDIUM" | "LOW"
    ema21: float
    ema50: float
    close: float
    atr_ratio: float
    evaluated_at: str   # ISO timestamp


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
    btc_trend: str | None = None
    btc_filter_applied: bool = False


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


_btc_context_cache: BtcContext | None = None
_btc_context_cache_scan_id: str | None = None
_btc_binance_client: BinanceClient | None = None


def _get_binance_client() -> BinanceClient:
    global _btc_binance_client
    if _btc_binance_client is None:
        _btc_binance_client = BinanceClient()
    return _btc_binance_client


def get_btc_context(scan_id: str | None = None) -> BtcContext:
    """
    Retorna el contexto de BTC para el ciclo actual.
    Se evalúa una sola vez por scan_id (cache local en el proceso).
    """
    global _btc_context_cache, _btc_context_cache_scan_id

    if scan_id and _btc_context_cache is not None and _btc_context_cache_scan_id == scan_id:
        return _btc_context_cache

    client = _get_binance_client()
    df = enrich_dataframe(client.get_klines_df("BTCUSDT", "30m", 100))

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
    atr_ratio = (atr_current / atr_avg) if atr_avg > 0 else 0.0

    if atr_ratio > 1.3:
        volatility = "HIGH"
    elif atr_ratio > 0.7:
        volatility = "MEDIUM"
    else:
        volatility = "LOW"

    ctx = BtcContext(
        trend=trend,
        volatility=volatility,
        ema21=round(ema21, 4),
        ema50=round(ema50, 4),
        close=round(close, 4),
        atr_ratio=round(atr_ratio, 4),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )
    _btc_context_cache = ctx
    _btc_context_cache_scan_id = scan_id

    logger.info(
        json.dumps(
            {
                "event_type": "btc_context",
                "scan_id": scan_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trend": trend,
                "volatility": volatility,
                "ema21": ctx.ema21,
                "ema50": ctx.ema50,
                "close": ctx.close,
                "atr_ratio": ctx.atr_ratio,
            }
        )
    )
    return ctx


class MarketContextEvaluator:
    @staticmethod
    def evaluate(
        df: pd.DataFrame,
        pair: str,
        scan_id: str | None = None,
        pair_config: dict | None = None,
    ) -> MarketContext:
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

        # Filtro individual del par
        tradeable_individual = (
            trend == "BULLISH"
            and volatility in ("MEDIUM", "HIGH")
            and volume_state == "ACTIVE"
            and atr_viable
            and not bb_squeeze
        )

        tier = pair_config.get("tier", "1") if pair_config else "1"

        # Si no pasa el filtro individual, ni siquiera consultamos BTC
        if not tradeable_individual:
            ctx = MarketContext(
                pair=pair,
                trend=trend,
                volatility=volatility,
                volume_state=volume_state,
                atr_viable=atr_viable,
                bb_squeeze=bb_squeeze,
                tradeable=False,
                reason=_build_reason(trend, volatility, volume_state, atr_viable, bb_squeeze),
                btc_trend=None,
                btc_filter_applied=False,
            )
        else:
            # Filtro global de BTC solo para altcoins
            es_btc = pair in ("BTCUSDT", "BTCUSDC", "BTCBUSD")
            btc_trend: str | None = None
            btc_filter_applied = False
            tradeable_final = True
            reason = "OK"

            if not es_btc:
                btc_ctx = get_btc_context(scan_id or "")
                btc_trend = btc_ctx.trend
                btc_filter_applied = True

                if btc_ctx.trend == "BEARISH":
                    tradeable_final = False
                    reason = "BTC BEARISH — altcoins en riesgo de correlacion"
                elif btc_ctx.trend == "SIDEWAYS" and trend == "SIDEWAYS":
                    tradeable_final = False
                    reason = "BTC SIDEWAYS + SIDEWAYS — doble lateral, no operar"
                elif btc_ctx.trend == "SIDEWAYS" and trend == "BULLISH":
                    logger.info(
                        "[CTX] %s BULLISH con BTC SIDEWAYS — oportunidad permitida con mayor cautela",
                        pair,
                    )

            ctx = MarketContext(
                pair=pair,
                trend=trend,
                volatility=volatility,
                volume_state=volume_state,
                atr_viable=atr_viable,
                bb_squeeze=bb_squeeze,
                tradeable=tradeable_individual and tradeable_final,
                reason=reason if not tradeable_final else _build_reason(
                    trend, volatility, volume_state, atr_viable, bb_squeeze
                ),
                btc_trend=btc_trend,
                btc_filter_applied=btc_filter_applied,
            )

        if scan_id:
            from src.core.audit import log_market_context

            vol_ratio = (float(df["volume"].iloc[-1]) / vol_avg) if vol_avg else 0.0
            bb_width_s = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]
            bb_w = float(bb_width_s.iloc[-1])
            bb_w_avg = float(bb_width_s.rolling(20).mean().iloc[-1])

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

