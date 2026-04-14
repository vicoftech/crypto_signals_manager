from __future__ import annotations

from dataclasses import asdict

from src.config import settings
from src.strategies.base import Opportunity


def with_risk(op: Opportunity, entry_actual_price: float) -> dict:
    sl_pct = (entry_actual_price - op.sl_price) / entry_actual_price
    if sl_pct <= 0:
        raise ValueError("Invalid SL for LONG")
    risk_usd = settings.capital_total * settings.risk_per_trade_pct
    position_size_usd = risk_usd / sl_pct
    rr_ratio = (op.tp2_price - entry_actual_price) / (entry_actual_price - op.sl_price)
    data = asdict(op)
    data.update(
        {
            "entry_actual_price": entry_actual_price,
            "sl_pct": sl_pct,
            "risk_usd": risk_usd,
            "position_size_usd": position_size_usd,
            "rr_ratio": rr_ratio,
            "trailing_activation": settings.trailing_activation,
            "trailing_step_pct": settings.trailing_step_pct,
        }
    )
    return data
