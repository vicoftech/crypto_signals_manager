from __future__ import annotations

from src.config import settings


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


def _resolve_tp3(trade: dict, entry_price: float, tp2_price: float, tp1_price: float, sl_price: float) -> float:
    raw = float(trade.get("tp3_price") or 0)
    if raw > 0:
        return raw
    risk = entry_price - sl_price
    if risk > 0:
        return entry_price + risk * 4.5
    return tp2_price + max((tp2_price - tp1_price), entry_price * 0.001)


def evaluate_sim_trade(trade: dict, current_price: float) -> tuple[str | None, dict]:
    entry_price = float(trade.get("entry_price", 0) or 0)
    if entry_price <= 0:
        return "INVALID_TRADE_DATA", {}

    sl_price = float(trade.get("sl_price", entry_price * 0.99) or entry_price * 0.99)
    tp1_price = float(trade.get("tp1_price", entry_price * 1.01) or entry_price * 1.01)
    tp2_price = float(trade.get("tp2_price", entry_price * 1.02) or entry_price * 1.02)
    tp3_price = _resolve_tp3(trade, entry_price, tp2_price, tp1_price, sl_price)

    updates: dict = excursion_updates(trade, current_price)
    trail_step = float(
        trade.get("trailing_tp1_tp3_step_pct") or settings.trailing_tp1_tp3_step_pct
    )

    # TP3 tiene prioridad sobre salida por trailing si ambos aplican en el mismo tick
    if trade.get("tp1_hit") and trade.get("trailing_activated") and current_price >= tp3_price:
        return "TP3", updates

    if trade.get("trailing_activated"):
        prev_sl = float(trade.get("trailing_sl_final", entry_price) or entry_price)
        new_sl = current_price * (1.0 - trail_step)
        merged_sl = max(prev_sl, new_sl)
        if merged_sl > prev_sl:
            updates["trailing_sl_final"] = merged_sl
        active_sl = float(updates.get("trailing_sl_final", merged_sl))
        if current_price <= active_sl:
            return "TRAILING_SL", updates

    if (not trade.get("trailing_activated")) and current_price <= sl_price:
        return "SL", updates
    if (not trade.get("tp1_hit")) and current_price >= tp1_price:
        updates["tp1_hit"] = True
        updates["trailing_activated"] = True
        updates["trailing_sl_final"] = entry_price
        return None, updates

    return None, updates
