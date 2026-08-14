from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.simulator import evaluate_sim_trade
from src.core.tp_ladder import should_time_stop, tp_price_for_level
from src.config import settings


def _base_trade():
    # TP a 1.0R step: entry 100, SL 99 → TP1=101, TP2=102, TP3=103
    return {
        "entry_price": 100.0,
        "sl_price": 99.0,
        "tp1_price": 101.0,
        "tp2_price": 102.0,
        "tp3_price": 103.0,
        "ladder_level": 0,
        "tp_max_level": 6,
        "active_stop_price": 99.0,
        "breakeven_armed": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "max_favorable_excursion": 100.0,
    }


def test_tp_step_one_r():
    assert abs(settings.tp_r_step - 1.0) < 1e-9
    assert tp_price_for_level(100.0, 99.0, 1) == 101.0
    assert tp_price_for_level(100.0, 99.0, 2) == 102.0
    assert tp_price_for_level(100.0, 99.0, 3) == 103.0


def test_ladder_advances_to_tp1_without_close():
    trade = _base_trade()
    close_reason, updates = evaluate_sim_trade(trade, 101.1)
    assert close_reason is None
    assert updates["ladder_level"] == 1
    assert updates["active_stop_price"] == 101.0
    assert updates["tp1_hit"] is True


def test_ladder_exits_at_tp1_floor():
    trade = {**_base_trade(), "ladder_level": 1, "active_stop_price": 101.0, "tp1_hit": True}
    reason, _ = evaluate_sim_trade(trade, 100.9)
    assert reason == "SL_TP1"


def test_ladder_advances_tp2_tp3():
    trade = {**_base_trade(), "ladder_level": 1, "active_stop_price": 101.0, "tp1_hit": True}
    reason, updates = evaluate_sim_trade(trade, 103.1)
    assert reason is None
    assert updates["ladder_level"] == 3
    assert updates["active_stop_price"] == 103.0


def test_breakeven_arms_at_0_7r():
    trade = _base_trade()
    # 0.7R = 100.7
    reason, updates = evaluate_sim_trade(trade, 100.7)
    assert reason is None
    assert updates.get("breakeven_armed") is True
    assert updates["active_stop_price"] == 100.0 * (1.0 - settings.be_fee_buffer_pct)


def test_breakeven_exit_reason():
    be_stop = 100.0 * (1.0 - settings.be_fee_buffer_pct)
    trade = {
        **_base_trade(),
        "breakeven_armed": True,
        "active_stop_price": be_stop,
    }
    reason, _ = evaluate_sim_trade(trade, be_stop - 0.01)
    assert reason == "BE"


def test_breakeven_does_not_lower_after_tp1():
    trade = {
        **_base_trade(),
        "ladder_level": 1,
        "active_stop_price": 101.0,
        "tp1_hit": True,
        "breakeven_armed": True,
    }
    reason, updates = evaluate_sim_trade(trade, 101.5)
    assert reason is None
    # stop stays at TP1 floor until TP2
    assert updates.get("active_stop_price", 101.0) >= 101.0


def test_time_stop_triggers():
    old = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    trade = {
        **_base_trade(),
        "started_at": old,
        "max_favorable_excursion": 100.1,  # 0.1R < 0.3
    }
    assert should_time_stop(trade) is True
    reason, _ = evaluate_sim_trade(trade, 100.05)
    assert reason == "TIME_STOP"


def test_time_stop_skipped_if_progress():
    old = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    trade = {
        **_base_trade(),
        "started_at": old,
        "max_favorable_excursion": 100.4,  # 0.4R >= 0.3
    }
    assert should_time_stop(trade) is False
    reason, updates = evaluate_sim_trade(trade, 100.4)
    # Puede armar BE (0.7R no alcanzado) o no cerrar
    assert reason is None
