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

    def as_dict(self) -> dict:
        out = {
            "capital_inicial": round(self.capital_inicial, 2),
            "pnl_cerrado": round(self.pnl_cerrado, 2),
            "capital_total": round(self.capital_total, 2),
            "capital_bloqueado": round(self.capital_bloqueado, 2),
            "capital_disponible": round(self.capital_disponible, 2),
            "posiciones_abiertas": self.posiciones_abiertas,
            "drawdown_actual": round(self.drawdown_actual, 4),
        }
        if self.equity_note:
            out["equity_note"] = self.equity_note
        return out


def get_capital_snapshot(trades_mgr: TradesManager | None = None, mode: str | None = None) -> CapitalSnapshot:
    """
    Calcula un snapshot de capital a partir de ConfigTable y TradesTable.

    - capital_inicial: valor fijo configurado (fallback a settings.capital_total)
    - capital_total: capital actual acumulado (ConfigTable.capital_total)
    - pnl_cerrado: capital_total - capital_inicial
    - capital_bloqueado: suma de position_size_usd de trades SIM abiertos
    - capital_disponible: capital_total - capital_bloqueado (SIM); en live = USDT libre en Binance.
    - equity_note: en live, aclara que el saldo es USDT spot (no NAV en alts).
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
    if is_live_mode(target_mode):
        # En live/live_test el sizing debe reflejar el saldo real/ficticio de Binance.
        try:
            bal = BinanceClient().get_spot_balance("USDT")
            capital_total = float(bal.get("total", 0) or 0)
            capital_disponible = float(bal.get("free", 0) or 0)
            capital_bloqueado = max(0.0, capital_total - capital_disponible)
            abiertos = trades.list_open(mode=target_mode)
            equity_note = (
                "Totales son saldo USDT en wallet spot (no NAV de posiciones en cripto)."
            )
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
            capital_bloqueado = 0.0
            abiertos = trades.list_open(mode=target_mode)
            equity_note = ""
    else:
        # capital_total dinámico mantenido por TradesManager._apply_net_pnl_to_capital
        capital_total = config.get_capital(settings.capital_total)
        abiertos = trades.list_open(mode="simulation")
        capital_bloqueado = sum(float(t.get("position_size_usd", 0) or 0) for t in abiertos)
        capital_disponible = capital_total - capital_bloqueado

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
    )

