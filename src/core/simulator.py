from __future__ import annotations

from src.config import settings


def evaluate_sim_trade(trade: dict, current_price: float) -> tuple[str | None, dict]:
    entry_price = float(trade.get("entry_price", 0) or 0)
    if entry_price <= 0:
        return "INVALID_TRADE_DATA", {}

    sl_price = float(trade.get("sl_price", entry_price * 0.99) or entry_price * 0.99)
    tp1_price = float(trade.get("tp1_price", entry_price * 1.01) or entry_price * 1.01)
    tp2_price = float(trade.get("tp2_price", entry_price * 1.02) or entry_price * 1.02)

    updates: dict = {}
    trailing_sl = trade.get("trailing_sl_final")
    sl_active = float(trailing_sl) if trade.get("trailing_activated") and trailing_sl is not None else sl_price

    mfe = float(trade.get("max_favorable_excursion", entry_price) or entry_price)
    mae = float(trade.get("max_adverse_excursion", entry_price) or entry_price)
    updates["max_favorable_excursion"] = max(mfe, current_price)
    updates["max_adverse_excursion"] = min(mae, current_price)

    if trade.get("trailing_activated"):
        new_sl = current_price * (1 - settings.trailing_step_pct)
        if new_sl > trade.get("trailing_sl_final", 0):
            updates["trailing_sl_final"] = new_sl
        if current_price <= trade.get("trailing_sl_final", sl_active):
            return "TRAILING_SL", updates

    if (not trade.get("trailing_activated")) and current_price <= sl_price:
        return "SL", updates
    if (not trade.get("tp1_hit")) and current_price >= tp1_price:
        updates["tp1_hit"] = True
        updates["trailing_activated"] = True
        updates["trailing_sl_final"] = entry_price
        return None, updates
    if trade.get("tp1_hit") and current_price >= tp2_price:
        return "TP2", updates
    return None, updates
