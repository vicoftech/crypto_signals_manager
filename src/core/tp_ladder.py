from __future__ import annotations

from src.config import settings


def risk_amount(entry_price: float, sl_price: float) -> float:
    return max(entry_price - sl_price, 0.0)


def tp_price_for_level(entry_price: float, sl_price: float, level: int) -> float:
    """Nivel 1 = 1.5R, 2 = 3R, ... (level * tp_r_step * risk)."""
    if level <= 0:
        return entry_price
    r = risk_amount(entry_price, sl_price)
    if r <= 0:
        return entry_price
    step = float(settings.tp_r_step)
    return entry_price + r * step * float(level)


def max_tp_level() -> int:
    return max(1, int(settings.max_tp_level))


def tp_max_price(entry_price: float, sl_price: float) -> float:
    return tp_price_for_level(entry_price, sl_price, max_tp_level())


def ladder_payload_defaults(entry_price: float, sl_price: float) -> dict:
    """Campos iniciales Caso 1 (escalera SL, una sola salida)."""
    mx = max_tp_level()
    return {
        "ladder_level": 0,
        "tp_max_level": mx,
        "active_stop_price": float(sl_price),
        "tp1_hit": False,
        "trailing_activated": False,
        "tp_max_price": tp_max_price(entry_price, sl_price),
    }


def evaluate_ladder_trade(trade: dict, current_price: float) -> tuple[str | None, dict]:
    """
    Caso 1: al alcanzar TPn sube active_stop al precio de TPn y apunta al siguiente.
    Cierre unico cuando precio <= active_stop (o SL inicial si aun no hubo TP1).
    """
    from src.core.simulator import excursion_updates

    entry = float(trade.get("entry_price", 0) or 0)
    if entry <= 0:
        return "INVALID_TRADE_DATA", {}

    sl = float(trade.get("sl_price", entry * 0.99) or entry * 0.99)
    level = int(trade.get("ladder_level") or 0)
    max_level = int(trade.get("tp_max_level") or max_tp_level())
    active_stop = float(trade.get("active_stop_price") or sl)

    updates: dict = excursion_updates(trade, current_price)

    floor = sl if level <= 0 else active_stop
    if current_price <= floor:
        if level <= 0:
            return "SL", updates
        return f"SL_TP{level}", updates

    new_level = level
    new_stop = active_stop
    while new_level < max_level:
        next_level = new_level + 1
        tp_px = tp_price_for_level(entry, sl, next_level)
        if trade.get(f"tp{next_level}_price"):
            tp_px = float(trade[f"tp{next_level}_price"])
        if current_price < tp_px:
            break
        new_level = next_level
        new_stop = tp_px

    if new_level > level:
        updates["ladder_level"] = new_level
        updates["active_stop_price"] = new_stop
        updates["tp1_hit"] = new_level >= 1
        updates["trailing_activated"] = new_level >= 1
        updates["trailing_sl_final"] = new_stop

    return None, updates
