from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.core.config_store import ConfigStore
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

    def as_dict(self) -> dict:
        return {
            "capital_inicial": round(self.capital_inicial, 2),
            "pnl_cerrado": round(self.pnl_cerrado, 2),
            "capital_total": round(self.capital_total, 2),
            "capital_bloqueado": round(self.capital_bloqueado, 2),
            "capital_disponible": round(self.capital_disponible, 2),
            "posiciones_abiertas": self.posiciones_abiertas,
            "drawdown_actual": round(self.drawdown_actual, 4),
        }


def get_capital_snapshot() -> CapitalSnapshot:
    """
    Calcula un snapshot de capital a partir de ConfigTable y TradesTable.

    - capital_inicial: valor fijo configurado (fallback a settings.capital_total)
    - capital_total: capital actual acumulado (ConfigTable.capital_total)
    - pnl_cerrado: capital_total - capital_inicial
    - capital_bloqueado: suma de risk_usd de trades SIM abiertos
    - capital_disponible: capital_total - capital_bloqueado
    """
    config = ConfigStore()
    trades = TradesManager()

    # capital_inicial: usamos una clave dedicada si existe, si no, el valor inicial de settings
    capital_inicial = config.get_number("capital_inicial", settings.capital_total)
    # capital_total dinámico mantenido por TradesManager._apply_net_pnl_to_capital
    capital_total = config.get_capital(settings.capital_total)
    pnl_cerrado = capital_total - capital_inicial

    abiertos = trades.list_open(mode="SIM")
    capital_bloqueado = sum(float(t.get("risk_usd", 0) or 0) for t in abiertos)
    capital_disponible = capital_total - capital_bloqueado

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
    )

