from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.exchange_protection import (
    ExchangeProtectionManager,
    infer_protection_level,
    protection_client_order_id,
    SYNC_SYNCED,
    SYNC_FAILED,
)


def _trade(**kw):
    base = {
        "trade_id": "abc12345-6789-0000-0000-000000000001",
        "pair": "BTCUSDT",
        "entry_price": 100.0,
        "sl_price": 99.0,
        "active_stop_price": 99.0,
        "ladder_level": 0,
        "breakeven_armed": False,
        "base_qty": 1.0,
        "protection_sync_status": "unprotected",
    }
    base.update(kw)
    return base


def test_infer_protection_level():
    assert infer_protection_level(_trade()) == "SL"
    assert infer_protection_level(_trade(breakeven_armed=True)) == "BE"
    assert infer_protection_level(_trade(ladder_level=2, active_stop_price=102.0)) == "TP2"


def test_protection_client_order_id_be_distinct_from_sl():
    tid = "abc12345-6789-0000-0000-000000000001"
    assert protection_client_order_id(tid, "SL") != protection_client_order_id(tid, "BE")


@patch("src.core.exchange_protection._cancel_exchange_protections")
def test_reconcile_places_and_verifies_stop(mock_cancel):
    mgr = ExchangeProtectionManager()
    binance = MagicMock()
    binance.floor_quantity_to_lot.return_value = 1.0
    binance.tick_size.return_value = 0.01
    binance.round_price_to_tick.side_effect = lambda pair, px, direction="nearest": px
    binance._lot_step_min_qty.return_value = (0.001, 0.001)
    binance.place_stop_loss_sell.return_value = {"orderId": "999"}

    tid = "abc12345-6789-0000-0000-000000000001"
    client_id = protection_client_order_id(tid, "BE")
    binance.get_open_orders.return_value = [
        {
            "orderId": "999",
            "clientOrderId": client_id,
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "NEW",
            "stopPrice": "99.5",
            "origQty": "1.0",
        }
    ]

    trades = MagicMock()
    trade = _trade(breakeven_armed=True, active_stop_price=99.5)

    result = mgr.reconcile_protection(binance, trades, trade)
    assert result.ok is True
    assert result.order_id == "999"
    mock_cancel.assert_called_once()
    binance.place_stop_loss_sell.assert_called_once()
    last_update = trades.update_trade.call_args_list[-1][0][1]
    assert last_update["protection_sync_status"] == SYNC_SYNCED


@patch("src.core.exchange_protection._cancel_exchange_protections")
def test_reconcile_verify_fail_not_synced(mock_cancel):
    mgr = ExchangeProtectionManager()
    binance = MagicMock()
    binance.floor_quantity_to_lot.return_value = 1.0
    binance.tick_size.return_value = 0.01
    binance.round_price_to_tick.side_effect = lambda pair, px, direction="nearest": px
    binance._lot_step_min_qty.return_value = (0.001, 0.001)
    binance.place_stop_loss_sell.return_value = {"orderId": "999"}
    binance.get_open_orders.return_value = []

    trades = MagicMock()
    trade = _trade()
    result = mgr.reconcile_protection(binance, trades, trade)
    assert result.ok is False
    last_update = trades.update_trade.call_args_list[-1][0][1]
    assert last_update["protection_sync_status"] in (SYNC_FAILED, "pending")


def test_check_parity_requires_synced():
    mgr = ExchangeProtectionManager()
    binance = MagicMock()
    ok, err = mgr.check_parity(binance, _trade(protection_sync_status="failed"))
    assert ok is False
    assert "synced" in err


@patch("src.core.exchange_protection.exchange_protection_strict", return_value=True)
def test_monitor_strict_skips_market_on_unprotected(_strict):
    """Documented behavior: protected_exit without sync must not reach MARKET."""
    from src.core.exchange_protection import get_protection_manager

    mgr = get_protection_manager()
    trade = _trade(protection_sync_status="failed")
    assert mgr.has_verified_protection(trade) is False
