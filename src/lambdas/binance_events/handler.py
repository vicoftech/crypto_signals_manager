from __future__ import annotations

from src.core.binance_client import BinanceClient
from src.core.mode import is_live_mode
from src.core.trades_manager import TradesManager

binance = BinanceClient()
trades = TradesManager()


def handler(event, context):
    trades.reset_trade_list_cache()
    payload = event.get("detail", event)
    data = payload.get("data", payload)
    if str(data.get("e", "")).lower() != "executionreport":
        return {"ok": True, "ignored": True}
    parsed = binance.parse_ws_event(data)
    order_id = str(parsed.get("order_id", "") or "")
    client_oid = str(parsed.get("client_order_id") or "")
    if not order_id:
        return {"ok": True, "ignored": True}

    status = str(parsed.get("status", "")).upper()
    side = str(parsed.get("side", "")).upper()
    symbol = str(parsed.get("symbol") or "").upper()

    # Salida: piernas OCO (TP3 limit / SL stop) antes que otras ventas (solo modo REAL)
    if status == "FILLED" and side == "SELL":
        exit_price = float(parsed.get("avg_price", 0) or 0)
        for t in trades.list_open():
            if not is_live_mode(t.get("mode")):
                continue
            tid = str(t.get("trade_id", ""))
            if str(t.get("binance_oco_limit_order_id", "")) == order_id:
                if exit_price <= 0:
                    exit_price = float(t.get("entry_price", 0) or 0)
                lvl = int(t.get("ladder_level") or t.get("tp_max_level") or 6)
                trades.close_trade(tid, f"TP{lvl}" if lvl <= 6 else "TP_MAX", exit_price)
                return {"ok": True, "closed_trade_id": tid, "via": "oco_ceiling"}
            if str(t.get("binance_oco_stop_order_id", "")) == order_id:
                if exit_price <= 0:
                    exit_price = float(t.get("entry_price", 0) or 0)
                trades.close_trade(tid, "SL", exit_price)
                return {"ok": True, "closed_trade_id": tid, "via": "oco_sl"}
            prot_oid = str(t.get("protection_order_id", "") or t.get("binance_stop_order_id", ""))
            if prot_oid and prot_oid == order_id:
                if exit_price <= 0:
                    exit_price = float(t.get("active_stop_price", 0) or 0)
                lvl = int(t.get("ladder_level") or 0)
                be = bool(t.get("breakeven_armed"))
                if lvl <= 0 and be:
                    reason = "BE"
                elif lvl <= 0:
                    reason = "SL"
                else:
                    reason = f"SL_TP{lvl}"
                trades.close_trade(tid, reason, exit_price)
                return {"ok": True, "closed_trade_id": tid, "via": "protection_stop"}
            if str(t.get("binance_stop_order_id", "")) == order_id:
                if exit_price <= 0:
                    exit_price = float(t.get("active_stop_price", 0) or 0)
                lvl = int(t.get("ladder_level") or 1)
                trades.close_trade(tid, f"SL_TP{lvl}", exit_price)
                return {"ok": True, "closed_trade_id": tid, "via": "ladder_stop"}
            if client_oid:
                from src.core.exchange_protection import protection_client_order_id, infer_protection_level

                tid_s = str(t.get("trade_id", ""))
                level = infer_protection_level(t)
                if client_oid == protection_client_order_id(tid_s, level):
                    if exit_price <= 0:
                        exit_price = float(t.get("active_stop_price", 0) or 0)
                    lvl = int(t.get("ladder_level") or 0)
                    be = bool(t.get("breakeven_armed"))
                    if lvl <= 0 and be:
                        reason = "BE"
                    elif lvl <= 0:
                        reason = "SL"
                    else:
                        reason = f"SL_TP{lvl}"
                    trades.close_trade(tid, reason, exit_price)
                    return {"ok": True, "closed_trade_id": tid, "via": "protection_client_id"}

        matched = None
        for t in trades.list_open():
            if not is_live_mode(t.get("mode")):
                continue
            if str(t.get("binance_exit_order_id", "")) == order_id:
                matched = t
                break
            if client_oid and str(t.get("pending_exit_client_order_id", "")) == client_oid:
                matched = t
                break

        if matched is None and symbol:
            candidates = [
                x
                for x in trades.list_open()
                if str(x.get("pair", "")).upper() == symbol and is_live_mode(x.get("mode"))
            ]
            if len(candidates) == 1:
                matched = candidates[0]

        if matched and str(matched.get("status", "")).upper() == "OPEN":
            tid = str(matched.get("trade_id"))
            if exit_price <= 0:
                exit_price = float(matched.get("entry_price", 0) or 0)
            trades.close_trade(tid, "MANUAL", exit_price)
            return {"ok": True, "closed_trade_id": tid, "via": "sell_fill"}

        return {"ok": True, "event": parsed, "matched": False}

    # Entrada u otros eventos del BUY por orderId de la compra (solo REAL)
    for t in trades.list_open():
        if not is_live_mode(t.get("mode")):
            continue
        if str(t.get("binance_order_id", "")) != order_id:
            continue
        if side == "BUY":
            trades.update_trade(
                str(t.get("trade_id")),
                {
                    "entry_order_status": status,
                    "entry_commission_usd": float(parsed.get("commission", 0) or 0),
                },
            )
            return {"ok": True, "updated_trade_id": str(t.get("trade_id")), "status": status}

    return {"ok": True, "event": parsed, "matched": False}
