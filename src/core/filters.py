from __future__ import annotations

from src.config import settings


def passes_quality_filters(op_data: dict) -> bool:
    if op_data["rr_ratio"] < settings.min_rr_ratio:
        return False
    if op_data["sl_pct"] > settings.max_sl_pct:
        return False
    return True


def needs_drift_recalc(entry_signal: float, current_price: float) -> bool:
    drift_pct = abs(current_price - entry_signal) / entry_signal
    return drift_pct > settings.entry_drift_max_pct
