from __future__ import annotations

from unittest.mock import patch

from src.core.trades_manager import TradesManager


def test_can_open_different_pairs_when_no_global_cap():
    tm = TradesManager()
    tm.get_open_live_trades = lambda: [{"pair": "BTCUSDT", "trade_id": "a", "status": "OPEN", "mode": "live_test"}]  # type: ignore[method-assign]
    tm.find_open_real_by_pair = lambda p: None if p == "ETHUSDT" else {"pair": "BTCUSDT"}  # type: ignore[method-assign]
    with patch("src.core.trades_manager.settings") as st:
        st.max_concurrent_live_open = 0
        ok, reason = tm.can_open_live_trade("ETHUSDT")
    assert ok is True
    assert reason == ""


def test_blocks_second_on_same_pair():
    tm = TradesManager()
    tm.get_open_live_trades = lambda: [{"pair": "BTCUSDT", "trade_id": "a"}]  # type: ignore[method-assign]
    tm.find_open_real_by_pair = lambda p: {"pair": p} if p == "BTCUSDT" else None  # type: ignore[method-assign]
    with patch("src.core.trades_manager.settings") as st:
        st.max_concurrent_live_open = 0
        ok, reason = tm.can_open_live_trade("BTCUSDT")
    assert ok is False
    assert "ya_hay_operacion_abierta" in reason


def test_global_cap_when_configured():
    tm = TradesManager()
    tm.get_open_live_trades = lambda: [{"pair": "BTCUSDT", "trade_id": "a"}]  # type: ignore[method-assign]
    tm.find_open_real_by_pair = lambda p: None  # type: ignore[method-assign]
    with patch("src.core.trades_manager.settings") as st:
        st.max_concurrent_live_open = 1
        ok, reason = tm.can_open_live_trade("ETHUSDT")
    assert ok is False
    assert "max_concurrent_live_open=1" in reason
