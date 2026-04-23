from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.core.auto_sim_utils import apply_sl_close_slippage, apply_trailing_close_slippage
from src.core.binance_client import BinanceClient
from src.core.config_store import ConfigStore
from src.core.pairs_manager import PairsManager
from src.core.simulator import evaluate_sim_trade
from src.core.telegram_client import TelegramClient
from src.core.market_session import format_market_session_from_iso
from src.core.trades_manager import TradesManager
from src.core.audit import log_trade_from_row
from src.core.accounting import format_accounting_line_short

trades = TradesManager()
binance = BinanceClient()
telegram = TelegramClient()
config_store = ConfigStore()
pairs = PairsManager()
logger = logging.getLogger()


def _dur_minutes(started: str, ended: str) -> int:
    try:
        sa = started.replace("Z", "+00:00") if started.endswith("Z") else started
        ea = ended.replace("Z", "+00:00") if ended.endswith("Z") else ended
        a = datetime.fromisoformat(sa)
        b = datetime.fromisoformat(ea)
        return max(0, int((b - a).total_seconds() // 60))
    except Exception:
        return 0


def handler(event, context):
    for _ in range(2):
        for trade in trades.get_open_sims():
            price = binance.get_price(trade["pair"])
            close_reason, updates = evaluate_sim_trade(trade, price)
            tid = trade["trade_id"]
            if updates:
                trades.update_trade(tid, updates)
                trade = trades.get_trade(tid) or trade
            if close_reason:
                exit_px = float(price)
                pair = str(trade.get("pair", ""))
                if close_reason == "TRAILING_SL" and trade.get("trailing_sl_final") is not None:
                    exit_px = apply_trailing_close_slippage(
                        float(trade["trailing_sl_final"]),
                        pair,
                    )
                elif close_reason == "SL":
                    # Ejecutar siempre en torno al nivel de SL, no al precio del check
                    sl_level = float(trade.get("sl_price", price) or price)
                    exit_px = apply_sl_close_slippage(sl_level, pair)
                trades.close_trade(tid, close_reason, exit_px)
                closed = trades.get_trade(tid) or {}
                mercado = closed.get("market_session") or format_market_session_from_iso(
                    str(closed.get("started_at", trade.get("started_at", "")))
                )
                capital = config_store.get_capital(1183.0)
                try:
                    log_trade_from_row(closed)
                except Exception:
                    logger.warning("audit log_trade_from_row failed", exc_info=True)
                net = float(closed.get("net_pnl_usd", 0) or 0)
                size = float(closed.get("position_size_usd", 100) or 100)
                pct = (net / size * 100.0) if size else 0.0
                r_mult = float(closed.get("r_multiple", closed.get("rr_actual", closed.get("rr_ratio", 0))) or 0)
                ended = str(closed.get("ended_at", ""))
                started = str(closed.get("started_at", ""))
                dur = _dur_minutes(started, ended)
                src = str(closed.get("sim_source", "") or "")
                if src.startswith("auto"):
                    st = pairs.get_pair(str(closed.get("pair", "")))
                    stats_line = ""
                    if st and st.sim_stats:
                        ss = st.sim_stats
                        stats_line = (
                            f"Stats {closed.get('pair')}: trades={ss.get('total_sim', 0)} "
                            f"win%={100 * ss.get('ganadoras', 0) / max(1, ss.get('total_sim', 1)):.0f}"
                        )
                    telegram.send_auto_sim_closed(
                        str(closed.get("pair", "")),
                        str(closed.get("strategy", "")),
                        float(closed.get("entry_price", 0) or 0),
                        float(closed.get("exit_price", exit_px) or exit_px),
                        net,
                        pct,
                        r_mult,
                        str(close_reason),
                        dur,
                        stats_line,
                    )
                else:
                    telegram.send_trade_update(
                        (
                            f"🔔 [SIM] Operacion cerrada\n"
                            f"{closed.get('pair', trade.get('pair'))} | {closed.get('strategy', trade.get('strategy'))}\n"
                            f"Mercado: {mercado}\n"
                            f"Motivo: {close_reason}\n"
                            f"Salida: {float(closed.get('exit_price', exit_px) or exit_px):.4f}\n"
                            f"P&L neto: {net:+.2f} USD\n"
                            f"Capital actual: {capital:.2f}\n\n"
                            f"{format_accounting_line_short()}"
                        )
                    )
                el = pairs.eligibility_for_pair(str(closed.get("pair", "")))
                if el.get("eligible"):
                    telegram.send_auto_trade_eligible_notice(str(closed.get("pair", "")), el)
        time.sleep(15)
    return {"ok": True}
