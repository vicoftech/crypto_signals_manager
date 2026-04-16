from __future__ import annotations

from dataclasses import asdict

from src.config import settings
from src.core.capital import get_capital_snapshot
from src.strategies.base import Opportunity


class InsufficientCapitalError(Exception):
    """Señala que no hay capital disponible suficiente para abrir una nueva posición."""


def with_risk(op: Opportunity, entry_actual_price: float) -> dict:
    """
    Calcula tamaño de posición y riesgo usando el capital ACTUAL, no el inicial estático.
    """
    sl_pct = (entry_actual_price - op.sl_price) / entry_actual_price
    if sl_pct <= 0:
        raise ValueError("Invalid SL for LONG")

    snap = get_capital_snapshot().as_dict()
    capital_total = snap["capital_total"]
    capital_disponible = snap["capital_disponible"]

    if capital_disponible <= 0:
        raise InsufficientCapitalError(
            f"Capital disponible: ${capital_disponible:.2f}. No se puede abrir nueva posicion."
        )

    # Riesgo teórico sobre capital total
    risk_usd = capital_total * settings.risk_per_trade_pct
    # Nunca arriesgar más del capital disponible
    if risk_usd > capital_disponible:
        risk_usd = capital_disponible

    if risk_usd <= 0:
        raise InsufficientCapitalError(
            f"Capital disponible insuficiente para riesgo minimo. disponible=${capital_disponible:.2f}"
        )

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

