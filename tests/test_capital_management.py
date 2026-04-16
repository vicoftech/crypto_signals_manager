from __future__ import annotations

from src.core.capital import get_capital_snapshot


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


