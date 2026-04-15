from __future__ import annotations

import pandas as pd


def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if "open_time" in df.columns and "timestamp" not in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["EMA_21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA_50"] = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    df["MACD_12_26_9"] = macd
    df["MACDs_12_26_9"] = signal
    df["MACDh_12_26_9"] = macd - signal

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["ATRr_14"] = tr.rolling(14).mean() / close

    bbm = close.rolling(20).mean()
    std = close.rolling(20).std()
    df["BBM_20_2.0"] = bbm
    df["BBU_20_2.0"] = bbm + (2.0 * std)
    df["BBL_20_2.0"] = bbm - (2.0 * std)
    return df
