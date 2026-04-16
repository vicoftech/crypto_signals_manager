from __future__ import annotations

from src.core.capital import get_capital_snapshot
from src.core.trades_manager import TradesManager


def test_capital_snapshot_has_expected_keys_and_relationships():
    snap = get_capital_snapshot().as_dict()

    # Claves básicas presentes
    for key in (
        "capital_inicial",
        "pnl_cerrado",
        "capital_total",
        "capital_bloqueado",
        "capital_disponible",
        "posiciones_abiertas",
        "drawdown_actual",
    ):
        assert key in snap

    # Relación capital_disponible = capital_total - capital_bloqueado
    assert snap["capital_disponible"] == snap["capital_total"] - snap["capital_bloqueado"]

    # Invariantes simples
    assert snap["posiciones_abiertas"] >= 0
    # Drawdown nunca negativo
    assert snap["drawdown_actual"] >= 0.0


def test_close_trade_never_loses_more_than_position_size(monkeypatch):
    # For in-memory mode (no Dynamo)
    monkeypatch.delenv("TRADES_TABLE_NAME", raising=False)
    monkeypatch.delenv("CONFIG_TABLE_NAME", raising=False)

    tm = TradesManager()
    trade_id = tm.open_trade(
        {
            "pair": "TESTUSDT",
            "entry_price": 100.0,
            "sl_price": 98.0,
            "position_size_usd": 1000.0,
            "risk_usd": 50.0,
            "entry_commission_usd": 1.0,
        },
        mode="SIM",
    )
    # Forzar un cierre muy por debajo del SL
    tm.close_trade(trade_id, "SL", exit_price=90.0)
    closed = tm.get_trade(trade_id)
    assert closed is not None
    # La pérdida neta está acotada a -position_size_usd (modelo spot)
    assert float(closed.get("net_pnl_usd")) >= -1000.0 - 1e-6


