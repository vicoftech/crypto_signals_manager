from __future__ import annotations

from src.core.simulator import evaluate_sim_trade


def test_simulator_hits_tp1_then_tp2():
    trade = {
        "entry_price": 100.0,
        "sl_price": 99.0,
        "tp1_price": 101.0,
        "tp2_price": 103.0,
        "tp1_hit": False,
        "trailing_activated": False,
    }
    close_reason, updates = evaluate_sim_trade(trade, 101.1)
    assert close_reason is None
    assert updates["tp1_hit"] is True
