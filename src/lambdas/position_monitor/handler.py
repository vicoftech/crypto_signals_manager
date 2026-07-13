from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from src.core.auto_sim_utils import apply_sl_close_slippage, apply_trailing_close_slippage
from src.core.binance_client import BinanceClient
from src.core.live_exit import (
    close_live_trade_with_market_sell,
    has_exchange_exit_protection,
    sync_ladder_stop_on_exchange,
)
from src.core.config_store import ConfigStore
from src.core.mode import MODE_SIMULATION, normalize_mode
from src.core.pairs_manager import PairsManager
from src.core.simulator import evaluate_sim_trade, excursion_updates
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
    motive_display = str(closed.get("close_reason_text") or close_reason or "")
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
            motive_display,
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
                f"Motivo: {motive_display}\n"
                f"Salida: {float(closed.get('exit_price', exit_px) or exit_px):.4f}\n"
                f"P&L neto: {net:+.2f} USD\n"
                f"Capital actual: {capital:.2f}\n\n"
                f"{format_accounting_line_short()}"
            )
        )
    el = pairs.eligibility_for_pair(str(closed.get("pair", "")))
    if el.get("eligible"):
        telegram.send_auto_trade_eligible_notice(str(closed.get("pair", "")), el)

    tid = str(closed.get("trade_id") or trade_fallback.get("trade_id") or "")
    if tid:
        trades.update_trade(tid, {"close_notified_at": datetime.now(timezone.utc).isoformat()})


def _was_closed_within_hours(row: dict, max_age_hours: float) -> bool:
    ended = str(row.get("ended_at") or "")
    if not ended:
        return False
    try:
        ea = ended.replace("Z", "+00:00") if ended.endswith("Z") else ended
        dt = datetime.fromisoformat(ea)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt <= timedelta(hours=max_age_hours)
    except Exception:
        return False


def _pending_close_notifications(max_age_hours: float) -> list[dict]:
    """Cierres en Dynamo sin aviso Telegram (p. ej. cerrados por eventos Binance)."""
    out: list[dict] = []
    for row in trades.list_trades():
        if str(row.get("status", "")).upper() != "CLOSED":
            continue
        if row.get("close_notified_at"):
            continue
        if not _was_closed_within_hours(row, max_age_hours):
            continue
        out.append(row)
    return out


def _minutes_since_iso(iso_ts: str | None) -> float:
    if not iso_ts:
        return 0.0
    try:
        v = str(iso_ts)
        if v.endswith("Z"):
            v = v.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
    except Exception:
        return 0.0


def _should_notify_exit_fail(last_notify_at: str | None, cooldown_min: float) -> bool:
    """Evita spam Telegram: un aviso por trade cada cooldown_min minutos."""
    if not last_notify_at:
        return True
    return _minutes_since_iso(last_notify_at) >= cooldown_min


def handler(event, context):
    trades.reset_trade_list_cache()

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
            if close_reason.startswith("SL_TP") or close_reason == "TRAILING_SL":
                if trade.get("active_stop_price") is not None:
                    exit_px = apply_trailing_close_slippage(
                        float(trade["active_stop_price"]),
                        pair,
                    )
                elif trade.get("trailing_sl_final") is not None:
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
        tid = trade["trade_id"]
        pair = str(trade["pair"])
        price = binance.get_price(pair)

        exc = excursion_updates(trade, price)
        if exc:
            trades.update_trade(tid, exc)
            trade = trades.get_trade(tid) or trade

        prev_level = int(trade.get("ladder_level") or 0)
        close_reason, updates = evaluate_sim_trade(trade, price)
        if close_reason == "INVALID_TRADE_DATA":
            continue
        if updates:
            trades.update_trade(tid, updates)
            trade = trades.get_trade(tid) or trade
        new_level = int(trade.get("ladder_level") or 0)
        if new_level > prev_level:
            stop_px = float(trade.get("active_stop_price") or 0)
            ok_sync, err_sync = sync_ladder_stop_on_exchange(
                binance, trades, trade, new_level, stop_px
            )
            if ok_sync:
                telegram.send_trade_update(
                    f"📍 Escalera TP{new_level} ({pair})\n"
                    f"SL en exchange ~ {stop_px:.4f}. Objetivo siguiente TP.\n"
                    "Salida unica al retroceder al piso."
                )
            else:
                telegram.send_trade_update(
                    f"⚠️ TP{new_level} en {pair} pero stop en exchange fallo: {err_sync[:100]}\n"
                    "Monitor cerrara por precio si retrocede."
                )
            trade = trades.get_trade(tid) or trade
        if not close_reason:
            if trade.get("close_signal_at"):
                trades.update_trade(tid, {"close_signal_at": ""})
            continue

        signal_at = str(trade.get("close_signal_at") or "")
        if not signal_at:
            signal_at = datetime.now(timezone.utc).isoformat()
            trades.update_trade(tid, {"close_signal_at": signal_at})
            trade = trades.get_trade(tid) or trade
        signal_age_min = _minutes_since_iso(signal_at)
        protection_grace_min = float(os.getenv("LIVE_EXIT_PROTECTION_GRACE_MINUTES", "10"))

        # Salida por SL / piso escalera: la orden en Binance define el fill (~risk_usd).
        # No vender MARKET inmediatamente si hay OCO/STOP; pero tampoco deferir para siempre
        # cuando los IDs de proteccion estan stale.
        if close_reason == "SL" or close_reason.startswith("SL_TP"):
            if has_exchange_exit_protection(trade):
                if signal_age_min < protection_grace_min:
                    logger.info(
                        "live exit defer exchange trade_id=%s pair=%s reason=%s age=%.1fm",
                        tid,
                        pair,
                        close_reason,
                        signal_age_min,
                    )
                    continue
                logger.warning(
                    "live exit stale protection trade_id=%s pair=%s reason=%s age=%.1fm; "
                    "fallback MARKET",
                    tid,
                    pair,
                    close_reason,
                    signal_age_min,
                )
            floor_px = float(
                trade.get("active_stop_price")
                if close_reason.startswith("SL_TP")
                else trade.get("sl_price")
                or price
            )
            if floor_px > 0:
                ok_stop, err_stop = sync_ladder_stop_on_exchange(
                    binance,
                    trades,
                    trade,
                    int(trade.get("ladder_level") or 0),
                    floor_px,
                )
                if ok_stop:
                    logger.info(
                        "live exit placed STOP trade_id=%s pair=%s @ %.6f",
                        tid,
                        pair,
                        floor_px,
                    )
                    continue
                logger.warning(
                    "live exit STOP failed trade_id=%s: %s; fallback MARKET",
                    tid,
                    err_stop,
                )

        exit_px = float(price)
        if close_reason.startswith("SL_TP") or close_reason == "TRAILING_SL":
            floor_px = float(
                trade.get("active_stop_price") or trade.get("trailing_sl_final") or price
            )
            exit_px = apply_trailing_close_slippage(floor_px, pair)
        elif close_reason == "SL":
            exit_px = apply_sl_close_slippage(float(trade.get("sl_price", price) or price), pair)

        ok, err = close_live_trade_with_market_sell(
            trades, binance, trade, close_reason, fallback_price=float(price)
        )
        if not ok:
            fail_count = int(trade.get("exit_fail_count") or 0) + 1
            now_iso = datetime.now(timezone.utc).isoformat()
            trades.update_trade(
                tid,
                {
                    "exit_fail_count": fail_count,
                    "exit_fail_last_at": now_iso,
                    "exit_fail_last_error": str(err)[:500],
                },
            )
            logger.error(
                "live exit MARKET SELL failed trade_id=%s count=%s: %s",
                tid,
                fail_count,
                err,
            )

            notify_cooldown_min = float(os.getenv("EXIT_FAIL_NOTIFY_COOLDOWN_MINUTES", "60"))
            max_fails = int(os.getenv("EXIT_FAIL_MAX_RETRIES", "12"))
            last_notify = str(trade.get("exit_fail_notify_at") or "")
            should_notify = _should_notify_exit_fail(last_notify, notify_cooldown_min)

            # Tras muchos fallos (tipico: sin BASE en testnet), cierra solo en Dynamo
            # para dejar de reintentar cada ciclo del monitor.
            if fail_count >= max_fails:
                trades.close_trade(tid, "MANUAL", float(price))
                trades.update_trade(
                    tid,
                    {
                        "close_reason_text": (
                            f"Cierre forzoso tras {fail_count} fallos de VENTA MARKET: {err}"
                        )[:500],
                        "exit_fail_notify_at": now_iso,
                    },
                )
                telegram.send_trade_update(
                    f"🛑 Cierre forzoso (sin venta en exchange)\n"
                    f"{pair} trade_id={tid}\n"
                    f"Fallos VENTA: {fail_count}\n"
                    f"Ultimo error: {str(err)[:180]}\n"
                    "Trade cerrado en Dynamo; revisa balance BASE en Binance."
                )
                continue

            if should_notify:
                trades.update_trade(tid, {"exit_fail_notify_at": now_iso})
                next_in = int(notify_cooldown_min)
                remaining = max(0, max_fails - fail_count)
                telegram.send_trade_update(
                    f"⚠️ Cierre automatico fallo (VENTA)\n{pair} trade_id={tid}\n"
                    f"Intento {fail_count}/{max_fails}\n"
                    f"{err}\n"
                    f"Revisa balance BASE y LOT_SIZE. "
                    f"No avisare de nuevo en ~{next_in} min "
                    f"(cierre forzoso en ~{remaining} reintentos)."
                )
            continue

        closed = trades.get_trade(tid) or {}
        exit_px = float(closed.get("exit_price") or price)
        _emit_closed_notifications(closed, trade, exit_px, close_reason)

    max_age = float(os.getenv("CLOSED_NOTIFY_MAX_AGE_HOURS", "72"))
    for row in _pending_close_notifications(max_age):
        tid = str(row.get("trade_id", ""))
        exit_px = float(row.get("exit_price") or 0)
        cr = str(row.get("close_reason") or "")
        try:
            _emit_closed_notifications(row, row, exit_px, cr)
        except Exception:
            logger.exception("aviso Telegram para cierre pendiente fallo trade_id=%s", tid)

    return {"ok": True}
