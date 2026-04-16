from __future__ import annotations

from dataclasses import asdict

from src.config import settings
from src.core.capital import get_capital_snapshot
from src.strategies.base import Opportunity


class InsufficientCapitalError(Exception):
    """Señala que no hay capital disponible suficiente para abrir una nueva posición."""


def with_risk(op: Opportunity, entry_actual_price: float) -> dict:
    """
    MODELO SPOT DIRECTO:
    - position_size_usd = capital_total * risk_pct  (monto invertido)
    - risk_usd = position_size_usd * sl_pct          (pérdida esperada al SL)
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

    amount_to_invest = capital_total * settings.risk_per_trade_pct
    if amount_to_invest > capital_disponible:
        raise InsufficientCapitalError(
            f"Capital insuficiente. disponible=${capital_disponible:.2f} requerido=${amount_to_invest:.2f}"
        )
    if amount_to_invest <= 0:
        raise InsufficientCapitalError(
            f"Capital disponible insuficiente para riesgo minimo. disponible=${capital_disponible:.2f}"
        )

    position_size_usd = amount_to_invest
    risk_usd = amount_to_invest * sl_pct
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

