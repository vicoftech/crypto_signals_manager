from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.core.indicators import enrich_dataframe
from src.core.market_context import MarketContext
from src.strategies.ema_pullback import EMAPullbackStrategy
from src.strategies.macd_cross import MACDCrossStrategy
from src.strategies.momentum import MomentumContinuationStrategy
from src.strategies.orb import ORBStrategy
from src.strategies.range_breakout import RangeBreakoutStrategy
from src.strategies.support_bounce import SupportBounceStrategy


def _ctx_ok() -> MarketContext:
    return MarketContext(
        pair="BTCUSDT",
        trend="BULLISH",
        volatility="HIGH",
        volume_state="ACTIVE",
        atr_viable=True,
        bb_squeeze=False,
        tradeable=True,
        reason="test",
    )


def _ctx_not_tradeable() -> MarketContext:
    return MarketContext(
        pair="BTCUSDT",
        trend="SIDEWAYS",
        volatility="LOW",
        volume_state="QUIET",
        atr_viable=False,
        bb_squeeze=True,
        tradeable=False,
        reason="test",
    )


def _klines_to_df(rows: list[dict]) -> pd.DataFrame:
    return enrich_dataframe(pd.DataFrame(rows))


# --- ORB ---


@patch("src.strategies.orb.pd.Timestamp.now")
def test_orb_fuera_de_ventana_horaria(mock_now):
    mock_now.return_value = pd.Timestamp("2026-04-14T08:00:00+00:00")
    df = _klines_to_df(
        [
            {
                "open_time": int(
                    (pd.Timestamp("2026-04-14", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 2000.0,
            }
            for i in range(20)
        ]
    )
    assert ORBStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


@patch("src.strategies.orb.pd.Timestamp.now")
def test_orb_sin_velas_del_dia(mock_now):
    mock_now.return_value = pd.Timestamp("2026-04-14T02:00:00+00:00")
    df = _klines_to_df(
        [
            {
                "open_time": int(
                    (pd.Timestamp("2026-04-13", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 2000.0,
            }
            for i in range(20)
        ]
    )
    assert ORBStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


@patch("src.strategies.orb.pd.Timestamp.now")
def test_orb_sin_ruptura(mock_now):
    day = pd.Timestamp("2026-04-14", tz="UTC")
    mock_now.return_value = pd.Timestamp("2026-04-14T02:00:00+00:00")
    rows = []
    for i in range(30):
        ot = int((day + pd.Timedelta(minutes=30 * i)).timestamp() * 1000)
        rows.append(
            {
                "open_time": ot,
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.2,
                "volume": 2000.0,
            }
        )
    df = _klines_to_df(rows)
    assert ORBStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


@patch("src.strategies.orb.pd.Timestamp.now")
def test_orb_sin_volumen(mock_now):
    day = pd.Timestamp("2026-04-14", tz="UTC")
    mock_now.return_value = pd.Timestamp("2026-04-14T02:00:00+00:00")
    rows = []
    for i in range(30):
        ot = int((day + pd.Timedelta(minutes=30 * i)).timestamp() * 1000)
        hi = 100.0 if i < 4 else 100.0
        rows.append(
            {
                "open_time": ot,
                "open": 99.0,
                "high": hi,
                "low": 98.0,
                "close": 101.0 if i == 29 else 99.5,
                "volume": 500.0,
            }
        )
    df = _klines_to_df(rows)
    assert ORBStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


@patch("src.strategies.orb.pd.Timestamp.now")
def test_orb_señal_valida(mock_now):
    day = pd.Timestamp("2026-04-14", tz="UTC")
    mock_now.return_value = pd.Timestamp("2026-04-14T02:00:00+00:00")
    rows = []
    for i in range(30):
        ot = int((day + pd.Timedelta(minutes=30 * i)).timestamp() * 1000)
        if i < 4:
            o, h, l, c, v = 99.0, 100.0, 98.5, 99.5, 3000.0
        else:
            o, h, l, c, v = 100.0, 101.0, 99.0, 100.5, 1500.0
        rows.append({"open_time": ot, "open": o, "high": h, "low": l, "close": c, "volume": v})
    rows[-1]["high"] = 105.0
    rows[-1]["close"] = 104.0
    rows[-1]["volume"] = 5000.0
    df = _klines_to_df(rows)
    opp = ORBStrategy().analyze(df, "BTCUSDT", _ctx_ok())
    assert opp is not None
    assert opp.strategy == "ORB"
    assert opp.sl_price == pytest.approx(98.5, rel=1e-2)


# --- Support bounce ---


def test_calcular_soporte_sin_cluster():
    s = pd.Series([100.0 + i * 2.0 for i in range(20)])
    assert SupportBounceStrategy._calcular_soporte(s) is None


def test_supportbounce_sin_soporte_valido():
    df = _klines_to_df(
        [
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 100.0 + i * 2.0,
                "close": 100.5,
                "volume": 1000.0,
            }
            for i in range(60)
        ]
    )
    assert SupportBounceStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_supportbounce_precio_cayendo():
    lows_cluster = [100.0, 100.1, 100.2, 100.15, 100.18] * 10
    rows = []
    for i in range(60):
        lo = lows_cluster[i] if i < len(lows_cluster) else 100.0
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 102.0,
                "high": 103.0,
                "low": lo,
                "close": 99.5,
                "volume": 2000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-1], "RSI_14"] = 35.0
    df.loc[df.index[-1], "close"] = 99.0
    df.loc[df.index[-1], "low"] = 100.0
    df.loc[df.index[-1], "open"] = 101.0
    df.loc[df.index[-1], "high"] = 101.5
    assert SupportBounceStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_supportbounce_rsi_alto():
    rows = []
    for i in range(60):
        lo = 100.0 if i % 5 == 0 else 101.0
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 101.0,
                "high": 103.0,
                "low": lo,
                "close": 102.0,
                "volume": 2000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-3:], "low"] = 100.0
    df.loc[df.index[-1], "RSI_14"] = 45.0
    df.loc[df.index[-1], "close"] = 101.0
    df.loc[df.index[-1], "open"] = 100.0
    df.loc[df.index[-1], "high"] = 102.0
    assert SupportBounceStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_supportbounce_sin_mecha():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.8,
                "close": 100.5,
                "volume": 2000.0,
            }
        )
    df = _klines_to_df(rows)
    for j in range(45, 60):
        df.loc[df.index[j], "low"] = 99.5
    df.loc[df.index[-1], "RSI_14"] = 35.0
    df.loc[df.index[-1], "close"] = 100.2
    df.loc[df.index[-1], "open"] = 99.9
    df.loc[df.index[-1], "high"] = 100.3
    df.loc[df.index[-1], "low"] = 99.85
    assert SupportBounceStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_supportbounce_señal_valida():
    rows = []
    base_low = 100.0
    for i in range(60):
        lo = base_low if i % 3 == 0 else 100.2
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.5,
                "high": 103.0,
                "low": lo,
                "close": 102.0,
                "volume": 2000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-3:], "low"] = base_low
    df.loc[df.index[-1], "RSI_14"] = 35.0
    df.loc[df.index[-1], "open"] = 100.2
    df.loc[df.index[-1], "close"] = 100.8
    df.loc[df.index[-1], "high"] = 101.0
    df.loc[df.index[-1], "low"] = 99.0
    opp = SupportBounceStrategy().analyze(df, "BTCUSDT", _ctx_ok())
    assert opp is not None
    assert opp.strategy == "SupportBounce"
    assert opp.sl_type == "sl_override"


# --- EMA pullback ---


def test_emapullback_sin_pullback():
    rows = []
    p = 100.0
    for i in range(60):
        p += 0.2
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": p,
                "high": p + 0.5,
                "low": p - 0.1,
                "close": p + 0.1,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    assert EMAPullbackStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_emapullback_cierre_bajo_ema():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 102.0,
                "low": 98.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    ema21_last = float(df["EMA_21"].iloc[-1])
    df.loc[df.index[-3], "low"] = ema21_last * 0.999
    df.loc[df.index[-1], "close"] = ema21_last * 0.99
    assert EMAPullbackStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_emapullback_vela_bajista():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 102.0,
                "low": 97.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    ema21 = df["EMA_21"]
    df.loc[df.index[-2], "low"] = float(ema21.iloc[-2]) * 0.999
    df.loc[df.index[-1], "close"] = float(ema21.iloc[-1]) * 1.01
    df.loc[df.index[-1], "open"] = float(df.loc[df.index[-1], "close"]) + 1.0
    assert EMAPullbackStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_emapullback_cuerpo_debil():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 102.0,
                "low": 97.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    ema21 = df["EMA_21"]
    df.loc[df.index[-2], "low"] = float(ema21.iloc[-2]) * 0.999
    df.loc[df.index[-1], "open"] = 100.0
    df.loc[df.index[-1], "close"] = 100.05
    df.loc[df.index[-1], "high"] = 100.1
    df.loc[df.index[-1], "low"] = 99.95
    assert EMAPullbackStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_emapullback_señal_valida():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0 + i * 0.05,
                "high": 102.0 + i * 0.05,
                "low": 97.0 + i * 0.05,
                "close": 100.5 + i * 0.05,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    ema21 = df["EMA_21"]
    df.loc[df.index[-2], "low"] = float(ema21.iloc[-2]) * 0.9995
    df.loc[df.index[-1], "open"] = float(ema21.iloc[-1]) * 0.998
    df.loc[df.index[-1], "close"] = float(ema21.iloc[-1]) * 1.02
    df.loc[df.index[-1], "high"] = float(df.loc[df.index[-1], "close"]) + 0.5
    df.loc[df.index[-1], "low"] = float(ema21.iloc[-1]) * 0.99
    opp = EMAPullbackStrategy().analyze(df, "BTCUSDT", _ctx_ok())
    assert opp is not None
    assert opp.strategy == "EMAPullback"
    assert opp.sl_price == float(df["low"].tail(3).min())


# --- MACD ---


def test_macdc_sin_cruce_real():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.01,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-1], "MACD_12_26_9"] = 1.0
    df.loc[df.index[-2], "MACD_12_26_9"] = 1.1
    df.loc[df.index[-1], "MACDs_12_26_9"] = 0.5
    df.loc[df.index[-2], "MACDs_12_26_9"] = 0.4
    assert MACDCrossStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_macdc_macd_positivo_sin_aceleracion():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.02,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-2], "MACD_12_26_9"] = 0.1
    df.loc[df.index[-2], "MACDs_12_26_9"] = 0.2
    df.loc[df.index[-1], "MACD_12_26_9"] = 0.5
    df.loc[df.index[-1], "MACDs_12_26_9"] = 0.4
    df.loc[df.index[-2], "MACDh_12_26_9"] = 0.2
    df.loc[df.index[-1], "MACDh_12_26_9"] = 0.1
    df.loc[df.index[-5], "EMA_50"] = float(df["EMA_50"].iloc[-1]) + 1.0
    assert MACDCrossStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_macdc_cruce_bajo_cero():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.01,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-2], "MACD_12_26_9"] = -0.5
    df.loc[df.index[-2], "MACDs_12_26_9"] = -0.3
    df.loc[df.index[-1], "MACD_12_26_9"] = -0.1
    df.loc[df.index[-1], "MACDs_12_26_9"] = -0.2
    e50 = df["EMA_50"]
    df.loc[df.index[-5], "EMA_50"] = float(e50.iloc[-5]) - 0.01
    assert MACDCrossStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is not None


def test_macdc_cruce_zona_cero():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    close = float(df["close"].iloc[-1])
    z = close * 0.0005
    df.loc[df.index[-2], "MACD_12_26_9"] = -z
    df.loc[df.index[-2], "MACDs_12_26_9"] = z
    df.loc[df.index[-1], "MACD_12_26_9"] = z * 0.5
    df.loc[df.index[-1], "MACDs_12_26_9"] = z * 0.3
    df.loc[df.index[-2], "MACDh_12_26_9"] = 0.01
    df.loc[df.index[-1], "MACDh_12_26_9"] = 0.02
    e50 = df["EMA_50"]
    df.loc[df.index[-5], "EMA_50"] = float(e50.iloc[-5]) * 0.999
    assert MACDCrossStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is not None


def test_macdc_cruce_acelerando():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.01,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-2], "MACD_12_26_9"] = 0.1
    df.loc[df.index[-2], "MACDs_12_26_9"] = 0.15
    df.loc[df.index[-1], "MACD_12_26_9"] = 0.4
    df.loc[df.index[-1], "MACDs_12_26_9"] = 0.2
    df.loc[df.index[-2], "MACDh_12_26_9"] = 0.05
    df.loc[df.index[-1], "MACDh_12_26_9"] = 0.15
    e50 = df["EMA_50"]
    df.loc[df.index[-5], "EMA_50"] = float(e50.iloc[-5]) * 0.999
    assert MACDCrossStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is not None


def test_macdc_ema50_bajista():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.01,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-2], "MACD_12_26_9"] = -0.5
    df.loc[df.index[-2], "MACDs_12_26_9"] = -0.4
    df.loc[df.index[-1], "MACD_12_26_9"] = -0.2
    df.loc[df.index[-1], "MACDs_12_26_9"] = -0.3
    df.loc[df.index[-5], "EMA_50"] = float(df["EMA_50"].iloc[-1]) + 2.0
    assert MACDCrossStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


# --- Range breakout ---


def test_rangebreakout_sin_rango_lateral():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    df = _klines_to_df(rows)
    assert RangeBreakoutStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_rangebreakout_sin_ruptura():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.1,
                "volume": 3000.0,
            }
        )
    df = _klines_to_df(rows)
    mx = float(df["high"].iloc[-11:-1].max())
    df.loc[df.index[-1], "close"] = mx * 0.99
    assert RangeBreakoutStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_rangebreakout_sin_volumen():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.1,
                "volume": 2000.0,
            }
        )
    df = _klines_to_df(rows)
    res = float(df["high"].iloc[-11:-1].max())
    df.loc[df.index[-1], "close"] = res + 0.1
    df.loc[df.index[-1], "high"] = res + 0.2
    df.loc[df.index[-1], "volume"] = 1.0
    assert RangeBreakoutStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_rangebreakout_cierre_debil():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 100.4,
                "low": 99.5,
                "close": 100.1,
                "volume": 3000.0,
            }
        )
    df = _klines_to_df(rows)
    res = float(df["high"].iloc[-11:-1].max())
    df.loc[df.index[-1], "high"] = res + 0.5
    df.loc[df.index[-1], "low"] = res - 0.1
    df.loc[df.index[-1], "close"] = (float(df.loc[df.index[-1], "high"]) + float(df.loc[df.index[-1], "low"])) / 2 - 0.01
    df.loc[df.index[-1], "volume"] = 5000.0
    assert RangeBreakoutStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_rangebreakout_señal_valida():
    rows = []
    for i in range(60):
        if i < 40:
            o, h, l, c, v = 100.0, 104.0, 96.0, 100.0, 2000.0
        else:
            o, h, l, c, v = 100.0, 100.25, 99.85, 100.05, 2500.0
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    df = _klines_to_df(rows)
    res = float(df["high"].iloc[-11:-1].max())
    df.loc[df.index[-1], "high"] = res + 0.15
    df.loc[df.index[-1], "low"] = res - 0.02
    df.loc[df.index[-1], "close"] = res + 0.08
    df.loc[df.index[-1], "volume"] = 6000.0
    opp = RangeBreakoutStrategy().analyze(df, "BTCUSDT", _ctx_ok())
    assert opp is not None
    assert opp.strategy == "RangeBreakout"


# --- Momentum ---


def test_momentum_vela_bajista():
    rows = []
    for i in range(60):
        o, c = (100.0, 101.0) if i != 57 else (101.0, 100.0)
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": o,
                "high": 102.0,
                "low": 99.0,
                "close": c,
                "volume": 1000.0 + i * 50,
            }
        )
    df = _klines_to_df(rows)
    assert MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_momentum_cuerpo_debil():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 100.1,
                "volume": 1000.0 + i * 50,
            }
        )
    df = _klines_to_df(rows)
    assert MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_momentum_impulso_chico():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.9,
                "close": 100.05,
                "volume": 1000.0 + i * 50,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-3], "open"] = 100.0
    df.loc[df.index[-3], "close"] = 100.02
    df.loc[df.index[-2], "open"] = 100.02
    df.loc[df.index[-2], "close"] = 100.04
    df.loc[df.index[-1], "open"] = 100.04
    df.loc[df.index[-1], "close"] = 100.06
    df.loc[df.index[-3:], "RSI_14"] = 55.0
    assert MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_momentum_rsi_alto():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0 + i * 0.1,
                "high": 101.0 + i * 0.1,
                "low": 99.5 + i * 0.1,
                "close": 100.5 + i * 0.1,
                "volume": 1000.0 + i * 100,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-1], "RSI_14"] = 75.0
    assert MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_momentum_rsi_bajo():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0 + i * 0.1,
                "high": 101.0 + i * 0.1,
                "low": 99.5 + i * 0.1,
                "close": 100.5 + i * 0.1,
                "volume": 1000.0 + i * 100,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-1], "RSI_14"] = 45.0
    assert MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_momentum_sin_volumen():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0 + i * 0.2,
                "high": 101.0 + i * 0.2,
                "low": 99.5 + i * 0.2,
                "close": 100.5 + i * 0.2,
                "volume": 500.0,
            }
        )
    df = _klines_to_df(rows)
    df.loc[df.index[-1], "volume"] = 100.0
    df.loc[df.index[-2], "volume"] = 200.0
    df.loc[df.index[-3], "volume"] = 300.0
    df.loc[df.index[-1], "RSI_14"] = 60.0
    assert MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok()) is None


def test_momentum_señal_valida():
    rows = []
    for i in range(60):
        rows.append(
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0 + i * 0.05,
                "high": 102.0 + i * 0.05,
                "low": 99.0 + i * 0.05,
                "close": 101.0 + i * 0.05,
                "volume": 1000.0 + i * 300,
            }
        )
    df = _klines_to_df(rows)
    o3 = float(df.loc[df.index[-3], "open"])
    df.loc[df.index[-3], "open"] = o3
    df.loc[df.index[-3], "close"] = o3 + 0.4
    df.loc[df.index[-3], "high"] = o3 + 0.5
    df.loc[df.index[-3], "low"] = o3 - 0.1
    df.loc[df.index[-2], "open"] = o3 + 0.4
    df.loc[df.index[-2], "close"] = o3 + 0.9
    df.loc[df.index[-2], "high"] = o3 + 1.0
    df.loc[df.index[-2], "low"] = o3 + 0.35
    df.loc[df.index[-1], "open"] = o3 + 0.9
    df.loc[df.index[-1], "close"] = o3 + 1.5
    df.loc[df.index[-1], "high"] = o3 + 1.6
    df.loc[df.index[-1], "low"] = o3 + 0.85
    df.loc[df.index[-3], "volume"] = 3000.0
    df.loc[df.index[-2], "volume"] = 4000.0
    df.loc[df.index[-1], "volume"] = 5000.0
    df.loc[df.index[-1], "RSI_14"] = 60.0
    opp = MomentumContinuationStrategy().analyze(df, "BTCUSDT", _ctx_ok())
    assert opp is not None
    assert opp.strategy == "Momentum"


def test_strategies_respect_not_tradeable():
    df = _klines_to_df(
        [
            {
                "open_time": int(
                    (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=30 * i)).timestamp() * 1000
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 2000.0,
            }
            for i in range(60)
        ]
    )
    ctx = _ctx_not_tradeable()
    assert EMAPullbackStrategy().analyze(df, "X", ctx) is None
    assert MACDCrossStrategy().analyze(df, "X", ctx) is None
