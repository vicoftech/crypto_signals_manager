from __future__ import annotations

import logging
import os
import time
import uuid

from src.config import settings
from src.core.binance_client import BinanceClient
from src.core.calculator import with_risk
from src.core.config_store import ConfigStore
from src.core.filters import needs_drift_recalc, passes_quality_filters
from src.core.indicators import enrich_dataframe
from src.core.market_context import MarketContextEvaluator
from src.core.pairs_manager import PairsManager
from src.core.state import CooldownState
from src.core.telegram_client import TelegramClient
from src.core.audit import log_opportunity, log_scan_cycle, log_strategy_execution
from src.strategies import STRATEGY_REGISTRY

logger = logging.getLogger()
logger.setLevel(logging.INFO)

binance = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET"))
pairs = PairsManager()
cooldown = CooldownState()
telegram = TelegramClient()
config_store = ConfigStore()


def handler(event, context):
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
            ctx = MarketContextEvaluator.evaluate(df, pair_cfg.pair, scan_id=scan_id)
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
                op_data = with_risk(opp, current_price)
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
        )
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
