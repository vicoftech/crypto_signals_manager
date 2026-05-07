from __future__ import annotations

from src.core.binance_client import BinanceClient
from src.core.trades_manager import TradesManager

binance = BinanceClient()
trades = TradesManager()


def handler(event, context):
    payload = event.get("detail", event)
    data = payload.get("data", payload)
    if str(data.get("e", "")).lower() != "executionreport":
        return {"ok": True, "ignored": True}
    parsed = binance.parse_ws_event(data)
    order_id = str(parsed.get("order_id", "") or "")
    if not order_id:
        return {"ok": True, "ignored": True}
    for t in trades.list_open():
        if str(t.get("binance_order_id", "")) != order_id:
            continue
        status = str(parsed.get("status", "")).upper()
        side = str(parsed.get("side", "")).upper()
        if status == "FILLED" and side == "SELL" and str(t.get("status", "")).upper() == "OPEN":
            # Sell fill is treated as exit execution.
            exit_price = float(parsed.get("avg_price", t.get("entry_price", 0)) or 0)
            trades.close_trade(str(t.get("trade_id")), "MANUAL", exit_price)
            return {"ok": True, "closed_trade_id": str(t.get("trade_id"))}
        trades.update_trade(
            str(t.get("trade_id")),
            {
                "entry_order_status": status,
                "entry_commission_usd": float(parsed.get("commission", 0) or 0),
            },
        )
        return {"ok": True, "updated_trade_id": str(t.get("trade_id")), "status": status}
    return {"ok": True, "event": parsed, "matched": False}
