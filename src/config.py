from __future__ import annotations

import os
from dataclasses import dataclass

from src.core.secrets import get_binance_secret_payload


def binance_credentials_configured() -> bool:
    """REAL mode requires signed Binance API access (listenKey, user stream)."""
    key = (os.getenv("BINANCE_API_KEY") or "").strip()
    secret = (os.getenv("BINANCE_SECRET") or "").strip()
    if key and secret:
        return True
    payload = get_binance_secret_payload()
    key = str(payload.get("api_key", "")).strip()
    secret = str(payload.get("api_secret", "")).strip()
    return bool(key and secret)


@dataclass(frozen=True)
class Settings:
    capital_total: float = float(os.getenv("CAPITAL_TOTAL", "1100.0"))
    risk_per_trade_pct: float = min(float(os.getenv("RISK_PER_TRADE_PCT", "0.05")), 0.10)
    min_rr_ratio: float = float(os.getenv("MIN_RR_RATIO", "2.5"))
    max_sl_pct: float = float(os.getenv("MAX_SL_PCT", "0.01"))
    # SL fijo en % del entry (LONG). Si >0, with_risk fuerza este SL y recalcula TPs.
    fixed_sl_pct: float = float(os.getenv("FIXED_SL_PCT", "0.01"))
    # Si true, el tamaño usa capital_total de config. Si false, USDT libre Binance (compound real).
    sizing_use_config_capital: bool = os.getenv("SIZING_USE_CONFIG_CAPITAL", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    trailing_activation: float = float(os.getenv("TRAILING_ACTIVATION", "1.0"))
    trailing_step_pct: float = float(os.getenv("TRAILING_STEP_PCT", "0.005"))
    trailing_tp1_tp3_step_pct: float = float(os.getenv("TRAILING_TP1_TP3_STEP_PCT", "0.03"))
    tp_r_step: float = float(os.getenv("TP_R_STEP", "1.0"))
    max_tp_level: int = int(os.getenv("MAX_TP_LEVEL", "6"))
    # 0 = sin tope global (solo una op por par + capital disponible). >0 = max ops live en total.
    max_concurrent_live_open: int = max(0, int(os.getenv("MAX_CONCURRENT_LIVE_OPEN", "0")))
    entry_drift_max_pct: float = float(os.getenv("ENTRY_DRIFT_MAX_PCT", "0.003"))
    cooldown_minutes: int = int(os.getenv("COOLDOWN_MINUTES", "90"))
    be_enabled: bool = os.getenv("BE_ENABLED", "true").strip().lower() in ("1", "true", "yes")
    be_r_threshold: float = float(os.getenv("BE_R_THRESHOLD", "0.7"))
    be_fee_buffer_pct: float = float(os.getenv("BE_FEE_BUFFER_PCT", "0.0005"))
    time_stop_enabled: bool = os.getenv("TIME_STOP_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    time_stop_hours: float = float(os.getenv("TIME_STOP_HOURS", "3"))
    time_stop_min_r: float = float(os.getenv("TIME_STOP_MIN_R", "0.3"))
    # Corte temprano: si tras N horas el MFE sigue bajo, salir (antes del TIME_STOP pleno).
    time_stop_early_hours: float = float(os.getenv("TIME_STOP_EARLY_HOURS", "2"))
    time_stop_early_min_r: float = float(os.getenv("TIME_STOP_EARLY_MIN_R", "0.15"))
    # Si true, altcoins no abren con BTC SIDEWAYS (solo BULLISH).
    btc_require_bullish_for_alts: bool = os.getenv(
        "BTC_REQUIRE_BULLISH_FOR_ALTS", "true"
    ).strip().lower() in ("1", "true", "yes")
    ema_pullback_min_volume_ratio: float = float(os.getenv("EMA_PULLBACK_MIN_VOLUME_RATIO", "1.05"))
    ema_pullback_max_extension_pct: float = float(os.getenv("EMA_PULLBACK_MAX_EXTENSION_PCT", "0.006"))
    ema_pullback_min_close_in_range: float = float(os.getenv("EMA_PULLBACK_MIN_CLOSE_IN_RANGE", "0.60"))
    ema_pullback_max_range_pct: float = float(os.getenv("EMA_PULLBACK_MAX_RANGE_PCT", "0.018"))


settings = Settings()
