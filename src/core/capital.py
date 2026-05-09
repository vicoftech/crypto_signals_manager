from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.core.binance_client import BinanceClient
from src.core.config_store import ConfigStore
from src.core.mode import is_live_mode, normalize_mode, current_live_mode
from src.core.trades_manager import TradesManager


@dataclass
class CapitalSnapshot:
    capital_inicial: float
    pnl_cerrado: float
    capital_total: float
    capital_bloqueado: float
    capital_disponible: float
    posiciones_abiertas: int
    drawdown_actual: float
    equity_note: str = ""
    capital_context: str = "simulation"
    usdt_en_ordenes_binance: float = 0.0

    def as_dict(self) -> dict:
        out = {
            "capital_inicial": round(self.capital_inicial, 2),
            "pnl_cerrado": round(self.pnl_cerrado, 2),
            "capital_total": round(self.capital_total, 2),
            "capital_bloqueado": round(self.capital_bloqueado, 2),
            "capital_disponible": round(self.capital_disponible, 2),
            "posiciones_abiertas": self.posiciones_abiertas,
            "drawdown_actual": round(self.drawdown_actual, 4),
            "capital_context": self.capital_context,
        }
        if self.equity_note:
            out["equity_note"] = self.equity_note
        if self.capital_context == "live_usdt":
            out["delta_usdt_vs_linea_base"] = round(self.pnl_cerrado, 2)
            out["usdt_en_ordenes_binance"] = round(self.usdt_en_ordenes_binance, 2)
        return out


def get_capital_snapshot(trades_mgr: TradesManager | None = None, mode: str | None = None) -> CapitalSnapshot:
    """
    Calcula un snapshot de capital a partir de ConfigTable y TradesTable.

    Simulation:
    - capital_total / disponible / bloqueado: modelo interno (total - nocional ops = disponible).
    - capital_bloqueado: suma position_size_usd de SIM abiertas.

    Live / live_test (capital_context live_usdt):
    - capital_total: saldo USDT total en Binance spot.
    - capital_disponible: USDT libre (para proxima compra MARKET).
    - capital_bloqueado: nocional comprometido segun libro (suma position_size_usd de ops abiertas).
    - usdt_en_ordenes_binance: USDT retenido por ordenes LIMIT pendientes (total-free USDT).
    - pnl_cerrado: solo Delta USDT vs linea base guardada; no es NAV ni suma de P&L de /resumen.
    """
    config = ConfigStore()
    trades = trades_mgr if trades_mgr is not None else TradesManager()

    target_mode = normalize_mode(mode) if mode is not None else current_live_mode()

    # capital_inicial: base para calcular PnL del modo operativo actual.
    capital_inicial = config.get_number("capital_inicial", settings.capital_total)
    capital_total = config.get_capital(settings.capital_total)
    capital_bloqueado = 0.0
    capital_disponible = capital_total
    abiertos = trades.list_open(mode="simulation")

    equity_note = ""
    capital_context = "simulation"
    usdt_en_ordenes_binance = 0.0
    if is_live_mode(target_mode):
        # En live/live_test el sizing debe reflejar el saldo real/ficticio de Binance.
        try:
            bal = BinanceClient().get_spot_balance("USDT")
            capital_total = float(bal.get("total", 0) or 0)
            capital_disponible = float(bal.get("free", 0) or 0)
            usdt_en_ordenes_binance = max(0.0, capital_total - capital_disponible)
            abiertos = trades.list_open(mode=target_mode)
            capital_bloqueado = sum(float(t.get("position_size_usd", 0) or 0) for t in abiertos)
            capital_context = "live_usdt"
            baseline_key = (
                "capital_inicial_live"
                if normalize_mode(target_mode) == "live"
                else "capital_inicial_live_test"
            )
            baseline = config.get_number(baseline_key, -1.0)
            if baseline <= 0:
                baseline = capital_total
                config.set_number(baseline_key, baseline)
            capital_inicial = baseline
        except Exception:
            # Fallback seguro: continuar con capital interno si Binance no responde.
            capital_total = config.get_capital(settings.capital_total)
            capital_disponible = capital_total
            abiertos = trades.list_open(mode=target_mode)
            capital_bloqueado = sum(float(t.get("position_size_usd", 0) or 0) for t in abiertos)
            equity_note = ""
            capital_context = "live_fallback"
            usdt_en_ordenes_binance = 0.0
    else:
        # capital_total dinámico mantenido por TradesManager._apply_net_pnl_to_capital
        capital_total = config.get_capital(settings.capital_total)
        abiertos = trades.list_open(mode="simulation")
        capital_bloqueado = sum(float(t.get("position_size_usd", 0) or 0) for t in abiertos)
        capital_disponible = capital_total - capital_bloqueado
        capital_context = "simulation"

    pnl_cerrado = capital_total - capital_inicial

    drawdown_actual = 0.0
    if capital_total < capital_inicial and capital_inicial > 0:
        drawdown_actual = (capital_inicial - capital_total) / capital_inicial

    return CapitalSnapshot(
        capital_inicial=capital_inicial,
        pnl_cerrado=pnl_cerrado,
        capital_total=capital_total,
        capital_bloqueado=capital_bloqueado,
        capital_disponible=capital_disponible,
        posiciones_abiertas=len(abiertos),
        drawdown_actual=drawdown_actual,
        equity_note=equity_note,
        capital_context=capital_context,
        usdt_en_ordenes_binance=usdt_en_ordenes_binance,
    )

