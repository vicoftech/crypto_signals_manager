from __future__ import annotations

from src.core.binance_client import BinanceClient
from src.core.trades_manager import TradesManager

binance = BinanceClient()
trades = TradesManager()


def handler(event, context):
    payload = event.get("detail", event)
    parsed = binance.parse_ws_event(payload)
    # Placeholder: reconciliation by binance_order_id should happen here.
    return {"ok": True, "event": parsed}
