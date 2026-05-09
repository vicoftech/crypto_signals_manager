from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.core.auto_sim_utils import apply_sl_close_slippage, apply_trailing_close_slippage
from src.core.binance_client import BinanceClient
from src.core.live_exit import close_live_trade_with_market_sell
from src.core.config_store import ConfigStore
from src.core.mode import MODE_SIMULATION, normalize_mode
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


def _trade_label(mode_raw: str | None) -> str:
    if normalize_mode(mode_raw) == MODE_SIMULATION:
        return "[SIM]"
    return f"[{normalize_mode(mode_raw).upper()}]"


def _emit_closed_notifications(
    closed: dict,
    trade_fallback: dict,
    exit_px: float,
    close_reason: str,
) -> None:
    mercado = closed.get("market_session") or format_market_session_from_iso(
        str(closed.get("started_at", trade_fallback.get("started_at", "")))
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
    label = _trade_label(closed.get("mode"))
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
                f"🔔 {label} Operacion cerrada\n"
                f"{closed.get('pair', trade_fallback.get('pair'))} | "
                f"{closed.get('strategy', trade_fallback.get('strategy'))}\n"
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


def handler(event, context):
    trades.reset_trade_list_cache()
    for _ in range(2):
        for trade in trades.get_open_sims():
            price = binance.get_price(trade["pair"])
            close_reason, updates = evaluate_sim_trade(trade, price)
            tid = trade["trade_id"]
            if close_reason == "INVALID_TRADE_DATA":
                continue
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
                    sl_level = float(trade.get("sl_price", price) or price)
                    exit_px = apply_sl_close_slippage(sl_level, pair)
                trades.close_trade(tid, close_reason, exit_px)
                closed = trades.get_trade(tid) or {}
                _emit_closed_notifications(closed, trade, exit_px, close_reason)

        for trade in trades.get_open_live_trades():
            price = binance.get_price(trade["pair"])
            close_reason, updates = evaluate_sim_trade(trade, price)
            tid = trade["trade_id"]
            if close_reason == "INVALID_TRADE_DATA":
                continue
            if updates:
                trades.update_trade(tid, updates)
                trade = trades.get_trade(tid) or trade
            if not close_reason:
                continue

            ok, err = close_live_trade_with_market_sell(
                trades, binance, trade, close_reason, fallback_price=float(price)
            )
            if not ok:
                logger.error("live exit MARKET SELL failed trade_id=%s: %s", tid, err)
                telegram.send_trade_update(
                    f"⚠️ Cierre automatico fallo (VENTA)\n{trade.get('pair')} trade_id={tid}\n"
                    f"{err}\n"
                    "Revisa balance BASE y LOT_SIZE; se reintentara en el proximo ciclo."
                )
                continue

            closed = trades.get_trade(tid) or {}
            exit_px = float(closed.get("exit_price") or price)
            _emit_closed_notifications(closed, trade, exit_px, close_reason)

        time.sleep(15)
    return {"ok": True}
