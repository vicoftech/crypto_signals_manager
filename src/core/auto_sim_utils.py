from __future__ import annotations

import copy
import random
from typing import Any

from src.config import settings

ENTRY_SLIPPAGE: dict[str, tuple[float, float]] = {
    "BTCUSDT": (0.0001, 0.0003),
    "ETHUSDT": (0.0001, 0.0004),
    "BNBUSDT": (0.0002, 0.0005),
    "SOLUSDT": (0.0003, 0.0008),
    "XRPUSDT": (0.0002, 0.0006),
}

TRAILING_CLOSE_SLIPPAGE: dict[str, float] = {
    "BTCUSDT": 0.0002,
    "ETHUSDT": 0.0002,
    "SOLUSDT": 0.0005,
    "XRPUSDT": 0.0004,
}

ENTRY_DELAY_SECONDS_AUTO = 5
ENTRY_DELAY_SECONDS_MANUAL = 180


def apply_slippage_to_op_data(op_data: dict[str, Any], pair: str, entry_mode: str) -> tuple[dict[str, Any], float]:
    """Ajusta precios de entrada/sl/tp por slippage LONG. Devuelve (op_data_mutado, slippage_pct)."""
    d = copy.deepcopy(op_data)
    signal = float(d["entry_actual_price"])
    min_slip, max_slip = ENTRY_SLIPPAGE.get(pair, (0.0005, 0.0015))
    if entry_mode == "manual":
        min_slip *= 2
        max_slip *= 3
    slip = random.uniform(min_slip, max_slip)
    shift = signal * slip
    ent = signal + shift
    d["entry_actual_price"] = ent
    d["sl_price"] = float(d["sl_price"]) + shift
    d["tp1_price"] = float(d["tp1_price"]) + shift
    d["tp2_price"] = float(d["tp2_price"]) + shift
    sl = float(d["sl_price"])
    tp2 = float(d["tp2_price"])
    if ent > sl:
        d["rr_ratio"] = (tp2 - ent) / (ent - sl)
        d["sl_pct"] = (ent - sl) / ent
        risk_usd = float(d.get("risk_usd", settings.capital_total * settings.risk_per_trade_pct))
        d["risk_usd"] = risk_usd
        d["position_size_usd"] = risk_usd / d["sl_pct"] if d["sl_pct"] > 0 else float(d.get("position_size_usd", 100))
    d["drift_pct"] = slip
    return d, slip


def apply_trailing_close_slippage(trailing_sl_price: float, pair: str) -> float:
    slip = TRAILING_CLOSE_SLIPPAGE.get(pair, 0.0008)
    return trailing_sl_price * (1.0 - slip)


def apply_sl_close_slippage(sl_price: float, pair: str) -> float:
    """
    Precio efectivo de ejecucion de un SL fijo: aplica un slippage minimo
    similar al trailing para aproximar una ejecucion realista.
    """
    slip = TRAILING_CLOSE_SLIPPAGE.get(pair, 0.0008)
    return sl_price * (1.0 - slip)


def is_signal_still_valid(signal_price: float, current_price: float, max_drift_pct: float = 0.003) -> bool:
    if signal_price <= 0:
        return False
    drift = abs(current_price - signal_price) / signal_price
    return drift <= max_drift_pct


def calcular_pnl_circunstancial(
    entry_price: float,
    current_price: float,
    position_size_usd: float,
    commission_entry_usd: float,
) -> tuple[float, float]:
    """P&L neto circunstancial y % sobre nocional. Comisión salida estimada 0.1%."""
    if entry_price <= 0:
        return 0.0, 0.0
    pnl_bruto = (current_price - entry_price) / entry_price * position_size_usd
    comision_salida_estimada = position_size_usd * 0.001
    pnl_neto = pnl_bruto - commission_entry_usd - comision_salida_estimada
    pnl_pct = (pnl_neto / position_size_usd * 100.0) if position_size_usd > 0 else 0.0
    return round(pnl_neto, 2), round(pnl_pct, 3)


def calcular_pnl_asegurado_trailing(
    entry_price: float,
    trailing_sl_price: float,
    position_size_usd: float,
    commission_entry_usd: float,
) -> tuple[float, float]:
    """P&L si se ejecuta el trailing SL al nivel guardado (con slippage de cierre aproximado)."""
    exit_eff = trailing_sl_price * 0.9995
    return calcular_pnl_circunstancial(entry_price, exit_eff, position_size_usd, commission_entry_usd)


def trade_payload_from_op_data(op: dict[str, Any], sim_source: str) -> dict[str, Any]:
    size = float(op["position_size_usd"])
    ent = float(op["entry_actual_price"])
    entry_comm = size * 0.001
    return {
        "pair": op["pair"],
        "strategy": op["strategy"],
        "timeframe": op.get("timeframe", "30m"),
        "tier": str(op.get("tier", "1")),
        "entry_price": ent,
        "sl_price": float(op["sl_price"]),
        "tp1_price": float(op["tp1_price"]),
        "tp2_price": float(op["tp2_price"]),
        "position_size_usd": size,
        "risk_usd": float(op.get("risk_usd", 0) or 0),
        "rr_ratio": float(op.get("rr_ratio", 0) or 0),
        "tp1_hit": False,
        "trailing_activated": False,
        "entry_commission_usd": entry_comm,
        "slippage_pct": float(op.get("drift_pct", 0) or 0),
        "sim_source": sim_source,
        "max_favorable_excursion": ent,
        "max_adverse_excursion": ent,
    }


def default_sim_stats() -> dict[str, Any]:
    return {
        "total_sim": 0,
        "ganadoras": 0,
        "perdedoras": 0,
        "pnl_total_usd": 0.0,
        "r_multiple_avg": 0.0,
        "last_updated": None,
    }


MINIMUM_TRADES_FOR_AUTO = 100
MINIMUM_WINRATE_FOR_AUTO = 0.45
MINIMUM_R_MULTIPLE_FOR_AUTO = 1.5


def check_auto_trade_eligibility(stats: dict[str, Any] | None) -> dict[str, Any]:
    """Evalúa elegibilidad a partir de sim_stats (sin async)."""
    s = stats or {}
    total = int(s.get("total_sim", 0) or 0)
    gan = int(s.get("ganadoras", 0) or 0)
    r_avg = float(s.get("r_multiple_avg", 0) or 0)
    winrate = gan / total if total > 0 else 0.0
    out: dict[str, Any] = {
        "total_trades": total,
        "winrate": winrate,
        "r_multiple_avg": r_avg,
        "eligible": False,
        "reason": "",
    }
    if total < MINIMUM_TRADES_FOR_AUTO:
        out["reason"] = f"Faltan {MINIMUM_TRADES_FOR_AUTO - total} trades"
        return out
    if winrate < MINIMUM_WINRATE_FOR_AUTO:
        out["reason"] = f"Winrate {winrate:.0%} < minimo {MINIMUM_WINRATE_FOR_AUTO:.0%}"
        return out
    if r_avg < MINIMUM_R_MULTIPLE_FOR_AUTO:
        out["reason"] = f"R multiple {r_avg:.2f} < minimo {MINIMUM_R_MULTIPLE_FOR_AUTO}"
        return out
    out["eligible"] = True
    out["reason"] = "Cumple todos los criterios"
    return out
