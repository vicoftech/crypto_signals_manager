from __future__ import annotations

import logging
import os
import time
import uuid

from src.config import settings
from src.core.binance_client import BinanceClient
from src.core.live_exit import attach_oco_protections
from src.core.exchange_protection import get_protection_manager
from src.core.tp_ladder import ladder_payload_defaults
from src.core.calculator import InsufficientCapitalError, with_risk
from src.core.config_store import ConfigStore
from src.core.filters import needs_drift_recalc, passes_quality_filters
from src.core.indicators import enrich_dataframe
from src.core.market_context import MarketContextEvaluator
from src.core.auto_sim_utils import (
    apply_slippage_to_op_data,
    is_signal_still_valid,
    trade_payload_from_op_data,
)
from src.core.pairs_manager import PairsManager
from src.core.state import CooldownState
from src.core.telegram_client import TelegramClient
from src.core.trades_manager import TradesManager
from src.core.audit import log_opportunity, log_scan_cycle, log_strategy_execution
from src.core.accounting import format_accounting_line_short
from src.core.mode import current_live_mode
from src.strategies import STRATEGY_REGISTRY

logger = logging.getLogger()
logger.setLevel(logging.INFO)

binance = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET"))
pairs = PairsManager()
trades = TradesManager()
cooldown = CooldownState()
telegram = TelegramClient()
config_store = ConfigStore()


def _open_real_trade_from_opportunity(op_data: dict) -> str:
    mode = current_live_mode()
    trade_id = str(uuid.uuid4())
    size = float(op_data.get("position_size_usd", 100.0) or 100.0)
    order = binance.place_market_buy(
        pair=str(op_data["pair"]),
        quote_qty_usd=size,
        new_client_order_id=trade_id,
    )
    fills = order.get("fills") or []
    first_fill = fills[0] if fills else {}
    executed_qty = float(order.get("executedQty", 0) or 0)
    quote_qty = float(order.get("cummulativeQuoteQty", size) or size)
    entry_price = quote_qty / max(executed_qty, 1e-9)
    payload = {
        "pair": str(op_data["pair"]),
        "strategy": str(op_data["strategy"]),
        "timeframe": str(op_data.get("timeframe", "30m")),
        "tier": str(op_data.get("tier", "1")),
        "entry_price": entry_price,
        "sl_price": float(op_data["sl_price"]),
        "tp1_price": float(op_data["tp1_price"]),
        "tp2_price": float(op_data["tp2_price"]),
        "tp3_price": float(op_data["tp3_price"]),
        "trailing_tp1_tp3_step_pct": float(
            op_data.get("trailing_tp1_tp3_step_pct") or settings.trailing_tp1_tp3_step_pct
        ),
        "base_qty": executed_qty,
        "position_size_usd": quote_qty,
        "risk_usd": float(op_data.get("risk_usd", 0) or 0),
        "rr_ratio": float(op_data.get("rr_ratio", 0) or 0),
        "rr_planned": float(op_data.get("rr_ratio", 0) or 0),
        **ladder_payload_defaults(entry_price, float(op_data["sl_price"])),
        "entry_commission_usd": float(first_fill.get("commission", quote_qty * 0.001) or 0),
        "entry_order_status": str(order.get("status", "")),
        "binance_order_id": str(order.get("orderId", "")),
        "binance_client_order_id": str(order.get("clientOrderId", trade_id)),
        "opportunity_id": str(op_data.get("opportunity_id", "")),
        "confluence": bool(op_data.get("confluence", False)),
        "market_trend": str(op_data.get("market_trend", "")),
        "market_volatility": str(op_data.get("market_volatility", "")),
        "max_favorable_excursion": entry_price,
        "max_adverse_excursion": entry_price,
    }
    tid = trades.open_trade(payload, mode=mode, trade_id=trade_id)
    pair_s = str(op_data["pair"])
    ok_oco, err_oco = attach_oco_protections(
        binance,
        trades,
        tid,
        pair_s,
        executed_qty,
        float(op_data["sl_price"]),
        float(op_data["tp3_price"]),
        entry_price=entry_price,
    )
    if ok_oco:
        logger.info("OCO colocado trade_id=%s", tid)
        row = trades.get_trade(tid) or {}
        verify = get_protection_manager().verify_oco_after_attach(binance, trades, row)
        if verify.ok:
            logger.info("OCO SL verificado trade_id=%s order=%s", tid, verify.order_id)
        else:
            telegram.send_trade_update(
                f"⚠️ OCO colocado pero SL no verificado ({pair_s}). "
                f"Monitor reintentara. {verify.error[:100]}"
            )
    else:
        logger.exception("OCO fallo para %s trade_id=%s: %s", pair_s, tid, err_oco)
        telegram.send_trade_update(
            f"⚠️ Compra ejecutada pero OCO SL/TP3 fallo ({pair_s}). "
            f"Monitor gestionara sin proteccion exchange. Error: {err_oco[:120]}"
        )
    return tid


def handler(event, context):
    trades.reset_trade_list_cache()
    if config_store.is_paused():
        logger.info("scanner paused")
        telegram.send_trade_update("Scanner pausado: no se ejecuto busqueda de oportunidades.")
        return {"ok": True, "sent": 0, "paused": True}

    scan_id = str(uuid.uuid4())
    t_start = time.perf_counter()

    total_pairs = 0
    tradeable_pairs = 0
    context_evals = 0
    strategies_skipped_no_tradeable = 0
    strategy_checks = 0
    filtered_out = 0
    sent = 0
    errors = 0
    active_pairs = pairs.get_active_pairs()
    for pair_cfg in active_pairs:
        total_pairs += 1
        try:
            df = enrich_dataframe(binance.get_klines_df(pair_cfg.pair, "30m", 150))
            ctx = MarketContextEvaluator.evaluate(
                df, pair_cfg.pair, scan_id=scan_id, pair_config={"tier": pair_cfg.tier}
            )
            context_evals += 1
            if not ctx.tradeable:
                strategies_skipped_no_tradeable += len(pair_cfg.strategies)
                logger.info("skip %s: %s", pair_cfg.pair, ctx.reason)
                continue
            tradeable_pairs += 1

            for strategy_name in pair_cfg.strategies:
                strategy_checks += 1
                strategy = STRATEGY_REGISTRY.get(strategy_name)
                if not strategy:
                    continue
                if cooldown.in_cooldown(pair_cfg.pair, strategy_name, settings.cooldown_minutes):
                    continue
                opp = strategy.analyze(df, pair_cfg.pair, ctx)
                if not opp:
                    log_strategy_execution(scan_id, pair_cfg.pair, strategy_name, "FALLO")
                    continue
                current_price = binance.get_price(pair_cfg.pair)
                if needs_drift_recalc(opp.entry_price, current_price):
                    opp.entry_price = current_price
                try:
                    op_data = with_risk(opp, current_price)
                    op_data["opportunity_id"] = str(uuid.uuid4())
                    op_data["market_trend"] = str(ctx.trend)
                    op_data["market_volatility"] = str(ctx.volatility)
                    if "confluence" not in op_data:
                        op_data["confluence"] = bool(
                            op_data.get("confluence", getattr(opp, "confluence", False))
                        )
                except InsufficientCapitalError as e:
                    logger.warning("[CAPITAL] %s %s — %s", pair_cfg.pair, strategy_name, e)
                    # Aviso resumido de capital insuficiente
                    try:
                        from src.core.capital import get_capital_snapshot

                        snap = get_capital_snapshot().as_dict()
                        required = snap["capital_disponible"] * settings.risk_per_trade_pct
                        telegram.send_capital_insuficiente(pair_cfg.pair, snap, required)
                    except Exception:
                        logger.exception("capital snapshot / aviso insuficiente fallo")
                    continue
                if not passes_quality_filters(op_data):
                    filtered_out += 1
                    log_strategy_execution(
                        scan_id,
                        pair_cfg.pair,
                        strategy_name,
                        "FALLO",
                        condicion_falla="filtros_calidad",
                        valor_condicion=f"rr={op_data.get('rr_ratio')} sl_pct={op_data.get('sl_pct')}",
                    )
                    continue

                auto_trade_enabled = bool(getattr(pair_cfg, "auto_trade", False))
                auto_trade_strategies = list(getattr(pair_cfg, "auto_trade_strategies", []) or [])
                strategy_allowed_for_auto = (
                    not auto_trade_strategies or strategy_name in auto_trade_strategies
                )
                if auto_trade_enabled and strategy_allowed_for_auto:
                    ok_open, open_reason = trades.can_open_live_trade(pair_cfg.pair)
                    if not ok_open:
                        logger.info(
                            "skip auto_trade %s %s: %s",
                            pair_cfg.pair,
                            strategy_name,
                            open_reason,
                        )
                        continue
                    try:
                        trade_id = _open_real_trade_from_opportunity(op_data)
                    except Exception as e:
                        logger.exception(
                            "auto_trade error on %s %s",
                            pair_cfg.pair,
                            strategy_name,
                        )
                        log_strategy_execution(
                            scan_id,
                            pair_cfg.pair,
                            strategy_name,
                            "FALLO",
                            condicion_falla="auto_trade_error",
                            valor_condicion=str(e)[:180],
                        )
                        continue
                    mode = current_live_mode()
                    telegram.send_trade_update(
                        "🤖 AUTO-TRADE REAL EJECUTADO\n"
                        f"{pair_cfg.pair} | {strategy_name}\n"
                        f"mode: {mode}\n"
                        f"trade_id: {trade_id}\n"
                        f"Entrada ref: {float(op_data.get('entry_actual_price', 0) or 0):.4f}"
                    )
                    log_opportunity(scan_id, op_data)
                    log_strategy_execution(scan_id, pair_cfg.pair, strategy_name, "OPORTUNIDAD")
                    cooldown.mark(pair_cfg.pair, strategy_name)
                    sent += 1
                else:
                    sim_mode = getattr(pair_cfg, "sim_mode", "manual")
                    if sim_mode == "auto":
                        signal_px = float(op_data["entry_actual_price"])
                        op_adj, _slip = apply_slippage_to_op_data(op_data, pair_cfg.pair, "auto")
                        cur_px = binance.get_price(pair_cfg.pair)
                        if not is_signal_still_valid(signal_px, cur_px):
                            log_strategy_execution(
                                scan_id,
                                pair_cfg.pair,
                                strategy_name,
                                "FALLO",
                                condicion_falla="drift_entrada",
                                valor_condicion=f"signal={signal_px} current={cur_px}",
                            )
                            continue
                        payload = trade_payload_from_op_data(op_adj, "auto_scanner")
                        trades.open_trade(payload, "simulation")
                        telegram.send_auto_sim_opened(op_adj)
                        log_opportunity(scan_id, op_adj)
                        log_strategy_execution(scan_id, pair_cfg.pair, strategy_name, "OPORTUNIDAD")
                        cooldown.mark(pair_cfg.pair, strategy_name)
                        sent += 1
                    elif sim_mode == "disabled":
                        telegram.send_opportunity_notify_only(op_data)
                        log_opportunity(scan_id, op_data)
                        log_strategy_execution(scan_id, pair_cfg.pair, strategy_name, "OPORTUNIDAD")
                        cooldown.mark(pair_cfg.pair, strategy_name)
                        sent += 1
                    else:
                        telegram.send_opportunity(op_data)
                        log_opportunity(scan_id, op_data)
                        log_strategy_execution(scan_id, pair_cfg.pair, strategy_name, "OPORTUNIDAD")
                        cooldown.mark(pair_cfg.pair, strategy_name)
                        sent += 1
        except Exception:
            errors += 1
            logger.exception("scanner error on %s", pair_cfg.pair)

    batch_count = int(config_store.get_number("scanner_batch_count", 0))
    agg_pairs = int(config_store.get_number("scanner_agg_pairs_activos", 0))
    agg_tradeable = int(config_store.get_number("scanner_agg_pairs_tradeables", 0))
    agg_context = int(config_store.get_number("scanner_agg_eval_contexto", 0))
    agg_skip_mercado = int(config_store.get_number("scanner_agg_estrategias_sin_mercado", 0))
    agg_checks = int(config_store.get_number("scanner_agg_chequeos", 0))
    agg_sent = int(config_store.get_number("scanner_agg_oportunidades", 0))
    agg_filtered = int(config_store.get_number("scanner_agg_filtradas", 0))
    agg_errors = int(config_store.get_number("scanner_agg_errores", 0))

    batch_count += 1
    agg_pairs += total_pairs
    agg_tradeable += tradeable_pairs
    agg_context += context_evals
    agg_skip_mercado += strategies_skipped_no_tradeable
    agg_checks += strategy_checks
    agg_sent += sent
    agg_filtered += filtered_out
    agg_errors += errors

    if batch_count >= 3:
        mode = current_live_mode()
        open_mode_trades = trades.list_open(mode=mode)
        if open_mode_trades:
            lines = [
                (
                    f"- {t.get('pair')} | {t.get('strategy')} | "
                    f"id={t.get('trade_id')} | desde={str(t.get('started_at', ''))[:16]}"
                )
                for t in open_mode_trades[:8]
            ]
            if len(open_mode_trades) > 8:
                lines.append(f"... y {len(open_mode_trades) - 8} mas")
            pos_section = (
                "\n\n────────\n"
                f"📌 POSICIONES ABIERTAS ({mode})\n\n"
                + "\n".join(lines)
            )
        else:
            pos_section = f"\n\n📌 Posiciones abiertas ({mode}): ninguna."

        summary = (
            "Resumen scanner (ultimos 3 escaneos)\n"
            f"- pares_activos: {agg_pairs}\n"
            f"- evaluaciones_contexto: {agg_context}\n"
            f"- pares_tradeables: {agg_tradeable}\n"
            f"- estrategias_omitidas_mercado: {agg_skip_mercado}\n"
            f"- chequeos_estrategia (solo si tradeable): {agg_checks}\n"
            f"- oportunidades_enviadas: {agg_sent}\n"
            f"- filtradas_calidad: {agg_filtered}\n"
            f"- errores: {agg_errors}"
        ) + pos_section
        summary = summary + "\n\n" + format_accounting_line_short()
        telegram.send_trade_update(summary)
        config_store.set_number("scanner_batch_count", 0)
        config_store.set_number("scanner_agg_pairs_activos", 0)
        config_store.set_number("scanner_agg_pairs_tradeables", 0)
        config_store.set_number("scanner_agg_eval_contexto", 0)
        config_store.set_number("scanner_agg_estrategias_sin_mercado", 0)
        config_store.set_number("scanner_agg_chequeos", 0)
        config_store.set_number("scanner_agg_oportunidades", 0)
        config_store.set_number("scanner_agg_filtradas", 0)
        config_store.set_number("scanner_agg_errores", 0)
    else:
        config_store.set_number("scanner_batch_count", batch_count)
        config_store.set_number("scanner_agg_pairs_activos", agg_pairs)
        config_store.set_number("scanner_agg_pairs_tradeables", agg_tradeable)
        config_store.set_number("scanner_agg_eval_contexto", agg_context)
        config_store.set_number("scanner_agg_estrategias_sin_mercado", agg_skip_mercado)
        config_store.set_number("scanner_agg_chequeos", agg_checks)
        config_store.set_number("scanner_agg_oportunidades", agg_sent)
        config_store.set_number("scanner_agg_filtradas", agg_filtered)
        config_store.set_number("scanner_agg_errores", agg_errors)

    dur_ms = int((time.perf_counter() - t_start) * 1000)
    log_scan_cycle(
        scan_id,
        {
            "pares_evaluados": total_pairs,
            "pares_operables": tradeable_pairs,
            "descartados_trend": 0,
            "descartados_volume": 0,
            "descartados_volatility": 0,
            "descartados_atr": 0,
            "descartados_squeeze": 0,
            "oportunidades_brutas": sent + filtered_out,
            "descartadas_rr": filtered_out,
            "descartadas_sl_pct": 0,
            "descartadas_cooldown": 0,
            "enviadas_telegram": sent,
            "errores": errors,
        },
        dur_ms,
    )
    return {"ok": True, "sent": sent, "pairs": total_pairs, "errors": errors}
