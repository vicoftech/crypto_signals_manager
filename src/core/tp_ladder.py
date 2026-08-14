from __future__ import annotations

from datetime import datetime, timezone

from src.config import settings


def risk_amount(entry_price: float, sl_price: float) -> float:
    return max(entry_price - sl_price, 0.0)


def tp_price_for_level(entry_price: float, sl_price: float, level: int) -> float:
    """Nivel 1 = 1.0R, 2 = 2.0R, ... (level * tp_r_step * risk) con TP_R_STEP default 1.0."""
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
        "breakeven_armed": False,
        "tp_max_price": tp_max_price(entry_price, sl_price),
    }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        v = str(ts).strip()
        if v.endswith("Z"):
            v = v.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def should_time_stop(trade: dict, now: datetime | None = None) -> bool:
    """
    True si el trade lleva TIME_STOP_HOURS sin progreso minimo hacia TP1.
    Solo aplica con ladder_level==0 y sin BE armado.
    """
    if not settings.time_stop_enabled:
        return False
    level = int(trade.get("ladder_level") or 0)
    if level > 0 or bool(trade.get("breakeven_armed")):
        return False
    entry = float(trade.get("entry_price", 0) or 0)
    sl = float(trade.get("sl_price", 0) or 0)
    r = risk_amount(entry, sl)
    if entry <= 0 or r <= 0:
        return False
    started = _parse_iso(str(trade.get("started_at") or ""))
    if not started:
        return False
    now_dt = now or datetime.now(timezone.utc)
    age_hours = max(0.0, (now_dt - started).total_seconds() / 3600.0)
    if age_hours < float(settings.time_stop_hours):
        return False
    mfe = float(trade.get("max_favorable_excursion") or entry or 0)
    progress_r = max(0.0, (mfe - entry) / r)
    return progress_r < float(settings.time_stop_min_r)


def evaluate_ladder_trade(trade: dict, current_price: float) -> tuple[str | None, dict]:
    """
    Caso 1: al alcanzar TPn sube active_stop al precio de TPn y apunta al siguiente.
    Cierre unico cuando precio <= active_stop (o SL inicial si aun no hubo TP1).
    BE anticipado a be_r_threshold R; TIME_STOP si estancado.
    """
    from src.core.simulator import excursion_updates

    entry = float(trade.get("entry_price", 0) or 0)
    if entry <= 0:
        return "INVALID_TRADE_DATA", {}

    sl = float(trade.get("sl_price", entry * 0.99) or entry * 0.99)
    level = int(trade.get("ladder_level") or 0)
    max_level = int(trade.get("tp_max_level") or max_tp_level())
    active_stop = float(trade.get("active_stop_price") or sl)
    be_armed = bool(trade.get("breakeven_armed"))

    updates: dict = excursion_updates(trade, current_price)
    trade_view = {**trade, **updates}

    # Time-stop antes de avanzar escalera (solo level 0 sin BE).
    if should_time_stop(trade_view):
        return "TIME_STOP", updates

    # Armar BE anticipado (antes de evaluar cierre, para que el piso refleje BE).
    r = risk_amount(entry, sl)
    if (
        settings.be_enabled
        and level <= 0
        and r > 0
        and not be_armed
        and current_price >= entry + float(settings.be_r_threshold) * r
    ):
        be_stop = entry * (1.0 - float(settings.be_fee_buffer_pct))
        # Nunca bajar el stop por debajo del SL original.
        be_stop = max(be_stop, sl)
        updates["active_stop_price"] = be_stop
        updates["breakeven_armed"] = True
        active_stop = be_stop
        be_armed = True

    floor = sl if level <= 0 and not be_armed else active_stop
    if level <= 0 and be_armed:
        floor = active_stop

    if current_price <= floor:
        if level <= 0:
            if be_armed:
                return "BE", updates
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
        # Tras TP1 el piso es TPn; BE queda obsoleto pero no bajamos el stop.
        if new_level >= 1:
            updates["breakeven_armed"] = True

    return None, updates
