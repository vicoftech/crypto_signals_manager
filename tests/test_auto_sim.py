import os

os.environ.setdefault("PAIRS_TABLE_NAME", "")
os.environ.setdefault("TRADES_TABLE_NAME", "")
os.environ.setdefault("CONFIG_TABLE_NAME", "")

from src.core.auto_sim_utils import (
    apply_slippage_to_op_data,
    calcular_pnl_circunstancial,
    check_auto_trade_eligibility,
    is_signal_still_valid,
)


def test_slippage_aumenta_entrada_long():
    op = {
        "pair": "BTCUSDT",
        "strategy": "EMAPullback",
        "timeframe": "30m",
        "tier": "1",
        "entry_actual_price": 100.0,
        "sl_price": 99.0,
        "tp1_price": 101.0,
        "tp2_price": 102.0,
        "position_size_usd": 1000.0,
        "risk_usd": 50.0,
        "rr_ratio": 2.0,
        "sl_pct": 0.01,
    }
    adj, slip = apply_slippage_to_op_data(op, "BTCUSDT", "auto")
    assert adj["entry_actual_price"] > 100.0
    assert slip > 0


def test_slippage_manual_mayor_que_auto():
    op = {
        "pair": "BTCUSDT",
        "strategy": "X",
        "timeframe": "30m",
        "tier": "1",
        "entry_actual_price": 100.0,
        "sl_price": 99.0,
        "tp1_price": 101.0,
        "tp2_price": 102.0,
        "position_size_usd": 1000.0,
        "risk_usd": 50.0,
        "rr_ratio": 2.0,
        "sl_pct": 0.01,
    }
    a1, s1 = apply_slippage_to_op_data(dict(op), "BTCUSDT", "auto")
    a2, s2 = apply_slippage_to_op_data(dict(op), "BTCUSDT", "manual")
    assert a2["entry_actual_price"] >= a1["entry_actual_price"]


def test_signal_drift_invalida():
    assert is_signal_still_valid(100.0, 100.2, 0.003) is True
    assert is_signal_still_valid(100.0, 104.0, 0.003) is False


def test_pnl_circunstancial_positivo():
    pnl, pct = calcular_pnl_circunstancial(100.0, 101.0, 1000.0, 1.0)
    assert pnl > 0


def test_pnl_circunstancial_negativo():
    pnl, pct = calcular_pnl_circunstancial(100.0, 99.0, 1000.0, 1.0)
    assert pnl < 0


def test_eligibility_insuficientes_trades():
    r = check_auto_trade_eligibility({"total_sim": 10, "ganadoras": 8, "r_multiple_avg": 2.0})
    assert r["eligible"] is False


def test_eligibility_cumple():
    r = check_auto_trade_eligibility(
        {"total_sim": 100, "ganadoras": 50, "r_multiple_avg": 2.0}
    )
    assert r["winrate"] == 0.5
    assert r["eligible"] is True
