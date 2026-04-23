from __future__ import annotations

import os
from dataclasses import dataclass


def binance_credentials_configured() -> bool:
    """REAL mode requires signed Binance API access (listenKey, user stream)."""
    key = (os.getenv("BINANCE_API_KEY") or "").strip()
    secret = (os.getenv("BINANCE_SECRET") or "").strip()
    return bool(key and secret)


@dataclass(frozen=True)
class Settings:
    capital_total: float = float(os.getenv("CAPITAL_TOTAL", "1183.0"))
    risk_per_trade_pct: float = min(float(os.getenv("RISK_PER_TRADE_PCT", "0.05")), 0.10)
    min_rr_ratio: float = float(os.getenv("MIN_RR_RATIO", "2.5"))
    max_sl_pct: float = float(os.getenv("MAX_SL_PCT", "0.02"))
    trailing_activation: float = float(os.getenv("TRAILING_ACTIVATION", "1.0"))
    trailing_step_pct: float = float(os.getenv("TRAILING_STEP_PCT", "0.005"))
    entry_drift_max_pct: float = float(os.getenv("ENTRY_DRIFT_MAX_PCT", "0.003"))
    cooldown_minutes: int = int(os.getenv("COOLDOWN_MINUTES", "45"))
    ema_pullback_min_volume_ratio: float = float(os.getenv("EMA_PULLBACK_MIN_VOLUME_RATIO", "1.05"))
    ema_pullback_max_extension_pct: float = float(os.getenv("EMA_PULLBACK_MAX_EXTENSION_PCT", "0.006"))
    ema_pullback_min_close_in_range: float = float(os.getenv("EMA_PULLBACK_MIN_CLOSE_IN_RANGE", "0.60"))
    ema_pullback_max_range_pct: float = float(os.getenv("EMA_PULLBACK_MAX_RANGE_PCT", "0.018"))


settings = Settings()
