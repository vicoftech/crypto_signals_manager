from __future__ import annotations

from src.core.simulator import evaluate_sim_trade


def _base_trade():
    return {
        "entry_price": 100.0,
        "sl_price": 99.0,
        "tp1_price": 101.5,
        "tp2_price": 103.0,
        "tp3_price": 104.5,
        "ladder_level": 0,
        "tp_max_level": 6,
        "active_stop_price": 99.0,
    }


def test_ladder_advances_to_tp1_without_close():
    trade = _base_trade()
    close_reason, updates = evaluate_sim_trade(trade, 101.6)
    assert close_reason is None
    assert updates["ladder_level"] == 1
    assert updates["active_stop_price"] == 101.5
    assert updates["tp1_hit"] is True


def test_ladder_exits_at_tp1_floor():
    trade = {**_base_trade(), "ladder_level": 1, "active_stop_price": 101.5, "tp1_hit": True}
    reason, _ = evaluate_sim_trade(trade, 101.4)
    assert reason == "SL_TP1"


def test_ladder_advances_tp2_tp3():
    trade = {**_base_trade(), "ladder_level": 1, "active_stop_price": 101.5, "tp1_hit": True}
    reason, updates = evaluate_sim_trade(trade, 104.6)
    assert reason is None
    assert updates["ladder_level"] == 3
    assert updates["active_stop_price"] == 104.5
