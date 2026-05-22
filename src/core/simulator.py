from __future__ import annotations

from src.core.tp_ladder import evaluate_ladder_trade


def excursion_updates(trade: dict, current_price: float) -> dict:
    entry_price = float(trade.get("entry_price", 0) or 0)
    if entry_price <= 0:
        return {}
    mfe = float(trade.get("max_favorable_excursion", entry_price) or entry_price)
    mae = float(trade.get("max_adverse_excursion", entry_price) or entry_price)
    return {
        "max_favorable_excursion": max(mfe, current_price),
        "max_adverse_excursion": min(mae, current_price),
    }


def evaluate_sim_trade(trade: dict, current_price: float) -> tuple[str | None, dict]:
    """Escalera TP Caso 1: SL al TP anterior, salida unica."""
    return evaluate_ladder_trade(trade, current_price)
