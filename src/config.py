from __future__ import annotations

import os
from dataclasses import dataclass


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


settings = Settings()
