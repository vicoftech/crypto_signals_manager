from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()

_EVENT_TO_ENV = {
    "market_context": "AUDIT_FIREHOSE_MARKET_CONTEXT",
    "strategy_execution": "AUDIT_FIREHOSE_STRATEGY_EXECUTIONS",
    "opportunity": "AUDIT_FIREHOSE_OPPORTUNITIES",
    "scan_cycle": "AUDIT_FIREHOSE_SCAN_CYCLES",
    "trade": "AUDIT_FIREHOSE_TRADES",
}

_firehose = None


def _firehose_client():
    global _firehose
    if _firehose is None:
        _firehose = boto3.client("firehose")
    return _firehose


def _emit_audit(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, default=str)
    logger.info(line)
    et = payload.get("event_type")
    if not isinstance(et, str):
        return
    env_key = _EVENT_TO_ENV.get(et)
    if not env_key:
        return
    stream = os.getenv(env_key, "").strip()
    if not stream:
        return
    data = (line + "\n").encode("utf-8")
    try:
        _firehose_client().put_record(DeliveryStreamName=stream, Record={"Data": data})
    except (ClientError, BotoCoreError):
        logger.exception("audit firehose put_record failed stream=%s", stream)


def _session() -> str:
    hora = datetime.now(timezone.utc).hour
    if 0 <= hora < 8:
        return "ASIA"
    if 8 <= hora < 13:
        return "LONDON"
    if 13 <= hora < 17:
        return "OVERLAP"
    return "NEW_YORK"


def log_market_context(scan_id: str, ctx: Any, valores: dict[str, Any]) -> None:
    _emit_audit(
        {
            "event_type": "market_context",
            "scan_id": scan_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": _session(),
            "pair": ctx.pair,
            "tier": getattr(ctx, "tier", "1"),
            "trend": ctx.trend,
            "volatility": ctx.volatility,
            "volume_state": ctx.volume_state,
            "atr_viable": ctx.atr_viable,
            "bb_squeeze": ctx.bb_squeeze,
            "tradeable": ctx.tradeable,
            **valores,
        }
    )


def log_strategy_execution(
    scan_id: str,
    pair: str,
    strategy: str,
    resultado: str,
    condicion_falla: str | None = None,
    valor_condicion: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "event_type": "strategy_execution",
        "scan_id": scan_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session": _session(),
        "pair": pair,
        "strategy": strategy,
        "resultado": resultado,
        "condicion_falla": condicion_falla,
        "valor_condicion": valor_condicion,
    }
    if extra:
        payload.update(extra)
    _emit_audit(payload)


def log_opportunity(scan_id: str, opp: dict[str, Any]) -> None:
    oid = opp.get("opportunity_id")
    if not oid:
        oid = str(uuid.uuid4())
    _emit_audit(
        {
            "event_type": "opportunity",
            "scan_id": scan_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": _session(),
            "opportunity_id": str(oid),
            "pair": opp.get("pair"),
            "tier": opp.get("tier", "1"),
            "strategy": opp.get("strategy"),
            "timeframe": opp.get("timeframe"),
            "entry_price": opp.get("entry_actual_price", opp.get("entry_price")),
            "sl_price": opp.get("sl_price"),
            "sl_pct": opp.get("sl_pct"),
            "sl_type": opp.get("sl_type", ""),
            "tp1_price": opp.get("tp1_price"),
            "tp2_price": opp.get("tp2_price"),
            "rr_ratio": opp.get("rr_ratio"),
            "risk_usd": opp.get("risk_usd"),
            "position_size_usd": opp.get("position_size_usd"),
            "confluence": bool(opp.get("confluence", False)),
            "market_trend": str(opp.get("market_trend", "")),
            "market_volatility": str(opp.get("market_volatility", "")),
            "drift_pct": float(opp.get("drift_pct") or 0.0),
        }
    )


def log_scan_cycle(scan_id: str, metricas: dict[str, Any], duracion_ms: int) -> None:
    _emit_audit(
        {
            "event_type": "scan_cycle",
            "scan_id": scan_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": _session(),
            "duracion_ms": duracion_ms,
            **metricas,
        }
    )


def log_trade_from_row(t: dict[str, Any]) -> None:
    """Emite evento trade compatible con Glue/Athena (campos opcionales con default)."""
    _emit_audit(
        {
            "event_type": "trade",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": _session(),
            "trade_id": t.get("trade_id", ""),
            "opportunity_id": t.get("opportunity_id", ""),
            "mode": t.get("mode", ""),
            "pair": t.get("pair", ""),
            "tier": t.get("tier", "1"),
            "strategy": t.get("strategy", ""),
            "timeframe": t.get("timeframe", ""),
            "entry_price": _f(t.get("entry_price")),
            "exit_price": _f(t.get("exit_price")),
            "sl_initial": _f(t.get("sl_price")),
            "sl_final": _f(t.get("sl_price")),
            "sl_type": str(t.get("sl_type", "")),
            "sl_pct": _f(t.get("sl_pct")),
            "tp1_price": _f(t.get("tp1_price")),
            "tp2_price": _f(t.get("tp2_price")),
            "tp1_hit": bool(t.get("tp1_hit", False)),
            "trailing_activated": bool(t.get("trailing_activated", False)),
            "close_reason": str(t.get("close_reason", "")),
            "gross_pnl": _f(t.get("gross_pnl_usd")),
            "net_pnl": _f(t.get("net_pnl_usd")),
            "commission": _f(t.get("commission_usd")),
            "r_multiple": _f(t.get("r_multiple")),
            "rr_planned": _f(t.get("rr_ratio")),
            "rr_actual": _f(t.get("rr_ratio")),
            "mfe": _f(t.get("max_favorable_excursion")),
            "mae": _f(t.get("max_adverse_excursion")),
            "duration_minutes": int(t.get("duration_minutes", 0) or 0),
            "market_trend": str(t.get("market_trend", "")),
            "market_volatility": str(t.get("market_volatility", "")),
            "confluence": bool(t.get("confluence", False)),
            "capital_at_open": _f(t.get("capital_at_open")),
            "risk_pct": _f(t.get("risk_pct")),
            "risk_usd": _f(t.get("risk_usd")),
            "position_size_usd": _f(t.get("position_size_usd")),
            "started_at": str(t.get("started_at", "")),
            "ended_at": str(t.get("ended_at", "")),
        }
    )


def _f(v: Any) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0
