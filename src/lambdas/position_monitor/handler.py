from __future__ import annotations

import time

from src.core.binance_client import BinanceClient
from src.core.config_store import ConfigStore
from src.core.simulator import evaluate_sim_trade
from src.core.telegram_client import TelegramClient
from src.core.market_session import format_market_session_from_iso
from src.core.trades_manager import TradesManager

trades = TradesManager()
binance = BinanceClient()
telegram = TelegramClient()
config_store = ConfigStore()


def handler(event, context):
    # Keep runtime comfortably below Lambda timeout (58s).
    for _ in range(2):
        for trade in trades.get_open_sims():
            price = binance.get_price(trade["pair"])
            close_reason, updates = evaluate_sim_trade(trade, price)
            if updates:
                trades.update_trade(trade["trade_id"], updates)
            if close_reason:
                trades.close_trade(trade["trade_id"], close_reason, price)
                closed = trades.get_trade(trade["trade_id"]) or {}
                mercado = closed.get("market_session") or format_market_session_from_iso(
                    str(closed.get("started_at", trade.get("started_at", "")))
                )
                capital = config_store.get_capital(1183.0)
                telegram.send_trade_update(
                    (
                        f"🔔 [SIM] Operacion cerrada\n"
                        f"{closed.get('pair', trade.get('pair'))} | {closed.get('strategy', trade.get('strategy'))}\n"
                        f"Mercado: {mercado}\n"
                        f"Motivo: {close_reason}\n"
                        f"Salida: {float(closed.get('exit_price', price) or price):.4f}\n"
                        f"P&L neto: {float(closed.get('net_pnl_usd', 0) or 0):+.2f} USD\n"
                        f"Capital actual: {capital:.2f}"
                    )
                )
        time.sleep(15)
    return {"ok": True}
