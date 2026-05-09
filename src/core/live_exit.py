from __future__ import annotations

from src.core.binance_client import BinanceClient, exit_order_client_id
from src.core.trades_manager import TradesManager


def avg_exit_from_sell_order(order: dict) -> float:
    eq = float(order.get("executedQty", 0) or 0)
    cq = float(order.get("cummulativeQuoteQty", 0) or 0)
    if eq > 0 and cq > 0:
        return cq / eq
    fills = order.get("fills") or []
    if fills:
        total_quote = sum(float(f.get("price", 0) or 0) * float(f.get("qty", 0) or 0) for f in fills)
        total_base = sum(float(f.get("qty", 0) or 0) for f in fills)
        if total_base > 0:
            return total_quote / total_base
    return 0.0


def close_live_trade_with_market_sell(
    trades: TradesManager,
    binance: BinanceClient,
    trade: dict,
    close_reason: str,
    fallback_price: float,
) -> tuple[bool, str]:
    """
    Venta MARKET en SPOT y cierre en Dynamo. fallback_price si la orden no devuelve precio medio.
    Devuelve (exito, mensaje_error_vacio_si_ok).
    """
    tid = str(trade.get("trade_id", ""))
    pair = str(trade.get("pair", ""))
    base_qty = float(trade.get("base_qty") or 0)
    if base_qty <= 0:
        ep = float(trade.get("entry_price") or 0)
        ps = float(trade.get("position_size_usd") or 0)
        base_qty = ps / max(ep, 1e-9)

    exit_coid = exit_order_client_id(tid)
    trades.update_trade(tid, {"pending_exit_client_order_id": exit_coid})
    try:
        sell_order = binance.place_market_sell(pair, base_qty, exit_coid)
    except Exception as e:
        trades.update_trade(tid, {"pending_exit_client_order_id": ""})
        return False, str(e)

    exit_px = avg_exit_from_sell_order(sell_order)
    if exit_px <= 0:
        exit_px = float(fallback_price)
    trades.update_trade(
        tid,
        {
            "binance_exit_order_id": str(sell_order.get("orderId", "")),
            "pending_exit_client_order_id": "",
        },
    )
    trades.close_trade(tid, close_reason, exit_px)
    return True, ""
