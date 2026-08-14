from __future__ import annotations

from dataclasses import asdict

from src.config import settings
from src.core.capital import get_capital_snapshot
from src.core.config_store import ConfigStore
from src.core.tp_ladder import ladder_payload_defaults, tp_price_for_level
from src.strategies.base import Opportunity


class InsufficientCapitalError(Exception):
    """Señala que no hay capital disponible suficiente para abrir una nueva posición."""


def _sizing_capital_disponible(snap: dict) -> float:
    """
    Base para tamaño de posicion.
    Si sizing_use_config_capital: usa capital_total de config menos bloqueado (sim 1100).
    En live, no supera el USDT libre de Binance.
    """
    blocked = float(snap.get("capital_bloqueado", 0) or 0)
    binance_free = float(snap.get("capital_disponible", 0) or 0)
    if settings.sizing_use_config_capital:
        cfg_total = ConfigStore().get_capital(settings.capital_total)
        available = max(0.0, cfg_total - blocked)
        ctx = str(snap.get("capital_context") or "")
        if ctx.startswith("live"):
            # No comprar mas USDT del libre en exchange.
            return min(available, binance_free) if binance_free > 0 else available
        return available
    return binance_free


def with_risk(op: Opportunity, entry_actual_price: float) -> dict:
    """
    MODELO SPOT (alineado con /capital y /riesgo):
    - position_size_usd = capital_sizing * risk_pct   (ej. 5% de 1100 → 55 USD)
    - SL fijo opcional: FIXED_SL_PCT (ej. 1%) → risk_usd ≈ position * 0.01
    - TPs a 1R, 2R, 3R, ... (TP_R_STEP)
    """
    entry = float(entry_actual_price)
    if entry <= 0:
        raise ValueError("Invalid entry")

    # SL: fijo al % configurado (default 1%), si no usa el de la estrategia.
    fixed = float(settings.fixed_sl_pct)
    if fixed > 0:
        sl_price = entry * (1.0 - fixed)
        sl_pct = fixed
        sl_type = f"fixed_{fixed:.4f}"
    else:
        sl_price = float(op.sl_price)
        sl_pct = (entry - sl_price) / entry
        sl_type = str(getattr(op, "sl_type", "strategy") or "strategy")
    if sl_pct <= 0 or sl_price <= 0 or sl_price >= entry:
        raise ValueError("Invalid SL for LONG")

    # Recalcular TPs sobre el SL efectivo (1R, 2R, 3R, ...).
    tp1 = tp_price_for_level(entry, sl_price, 1)
    tp2 = tp_price_for_level(entry, sl_price, 2)
    tp3 = tp_price_for_level(entry, sl_price, 3)

    snap = get_capital_snapshot().as_dict()
    capital_disponible = _sizing_capital_disponible(snap)

    if capital_disponible <= 0:
        raise InsufficientCapitalError(
            f"Capital disponible: ${capital_disponible:.2f}. No se puede abrir nueva posicion."
        )

    # Preferir risk_pct de ConfigTable si existe; si no, settings.
    risk_pct = ConfigStore().get_risk_pct(settings.risk_per_trade_pct)
    risk_pct = min(max(float(risk_pct), 0.0), 0.10)

    amount_to_invest = capital_disponible * risk_pct
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
    rr_ratio = (tp3 - entry) / (entry - sl_price) if (entry - sl_price) > 0 else 0.0
    data = asdict(op)
    data.update(
        {
            "entry_actual_price": entry,
            "sl_price": sl_price,
            "sl_type": sl_type,
            "tp1_price": tp1,
            "tp2_price": tp2,
            "tp3_price": tp3,
            "sl_pct": sl_pct,
            "risk_usd": risk_usd,
            "risk_pct": risk_pct,
            "position_size_usd": position_size_usd,
            "rr_ratio": rr_ratio,
            "trailing_activation": settings.trailing_activation,
            "trailing_step_pct": settings.trailing_step_pct,
            "trailing_tp1_tp3_step_pct": settings.trailing_tp1_tp3_step_pct,
            **ladder_payload_defaults(entry, sl_price),
        }
    )
    return data
