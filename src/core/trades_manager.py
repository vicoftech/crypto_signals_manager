from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import boto3

from src.config import settings
from src.core.market_session import format_market_session
from src.core.mode import MODE_SIMULATION, normalize_mode, is_simulation_mode, is_live_mode

logger = logging.getLogger(__name__)


class TradesManager:
    def __init__(self) -> None:
        self.table_name = os.getenv("TRADES_TABLE_NAME", "")
        self.config_table_name = os.getenv("CONFIG_TABLE_NAME", "")
        self.table = boto3.resource("dynamodb").Table(self.table_name) if self.table_name else None
        self.config_table = boto3.resource("dynamodb").Table(self.config_table_name) if self.config_table_name else None
        self._trades: dict[str, dict] = {}
        # Cache Dynamo scan/read within one invocation (cleared at Lambda entry where we reuse a singleton).
        self._list_cache: list[dict] | None = None

    def reset_trade_list_cache(self) -> None:
        """Llamar al inicio del handler cuando se usa un TradesManager singleton entre invocations."""
        self._list_cache = None

    def _invalidate_trade_list_cache(self) -> None:
        self._list_cache = None

    def open_trade(self, payload: dict, mode: str, trade_id: str | None = None) -> str:
        trade_id = trade_id or str(uuid4())
        started = datetime.now(timezone.utc)
        normalized_mode = normalize_mode(mode)
        row = {
            "trade_id": trade_id,
            "mode": normalized_mode,
            "status": "OPEN",
            "started_at": started.isoformat(),
            "market_session": format_market_session(started),
            **payload,
        }
        if self.table:
            self.table.put_item(Item=_to_dynamodb_types(row))
        self._trades[trade_id] = row
        self._invalidate_trade_list_cache()
        return trade_id

    def update_trade(self, trade_id: str, updates: dict) -> None:
        if not updates:
            return
        if trade_id not in self._trades:
            self._trades[trade_id] = {"trade_id": trade_id}
        self._trades[trade_id].update(updates)
        if self.table:
            expr_parts = []
            names = {}
            values = {}
            for idx, (k, v) in enumerate(updates.items(), start=1):
                nk = f"#k{idx}"
                vk = f":v{idx}"
                expr_parts.append(f"{nk}={vk}")
                names[nk] = k
                values[vk] = _to_dynamodb_types(v)
            self.table.update_item(
                Key={"trade_id": trade_id},
                UpdateExpression="SET " + ", ".join(expr_parts),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        self._invalidate_trade_list_cache()

    def get_trade(self, trade_id: str) -> dict | None:
        if self.table:
            item = self.table.get_item(Key={"trade_id": trade_id}).get("Item")
            return item
        return self._trades.get(trade_id)

    def close_trade(self, trade_id: str, close_reason: str, exit_price: float) -> None:
        trade = self.get_trade(trade_id) or {"trade_id": trade_id}
        if str(trade.get("status", "")).upper() == "CLOSED":
            return
        self._trades[trade_id] = trade
        entry = float(trade.get("entry_price", 0.0) or 0.0)
        size = float(trade.get("position_size_usd", 100.0) or 100.0)
        pnl_pct = ((exit_price - entry) / entry) if entry > 0 else 0.0
        gross_pnl = size * pnl_pct
        entry_comm = trade.get("entry_commission_usd")
        if entry_comm is not None and float(entry_comm) >= 0:
            entry_comm_f = float(entry_comm)
            exit_comm = size * 0.001
            commission = entry_comm_f + exit_comm
            net_pnl = gross_pnl - commission
        else:
            commission = size * 0.002
            net_pnl = gross_pnl - commission
        risk_usd = float(trade.get("risk_usd", 0) or 0)
        # Hard cap spot: la pérdida neta no puede superar el monto invertido
        if size > 0 and net_pnl < -size:
            logger.error(
                "[CAPITAL] Pérdida %.2f supera monto invertido %.2f en %s. "
                "Limitando a -position_size_usd.",
                net_pnl,
                size,
                trade.get("pair"),
            )
            net_pnl = -size
            # Recalcular P&L bruto aproximado manteniendo comisiones, solo para consistencia
            gross_pnl = net_pnl + commission
        r_mult = (net_pnl / risk_usd) if risk_usd > 0 else 0.0
        planned_rr = float(trade.get("rr_planned", trade.get("rr_ratio", 0)) or 0)
        reason_text = _close_reason_to_text(close_reason)
        self._trades[trade_id]["status"] = "CLOSED"
        self._trades[trade_id]["close_reason"] = close_reason
        self._trades[trade_id]["close_reason_text"] = reason_text
        self._trades[trade_id]["exit_price"] = exit_price
        self._trades[trade_id]["gross_pnl_usd"] = gross_pnl
        self._trades[trade_id]["commission_usd"] = commission
        self._trades[trade_id]["net_pnl_usd"] = net_pnl
        # Mantener RR planeado y guardar métricas reales por separado.
        self._trades[trade_id]["rr_ratio"] = planned_rr
        self._trades[trade_id]["rr_planned"] = planned_rr
        self._trades[trade_id]["rr_actual"] = r_mult
        self._trades[trade_id]["r_multiple"] = r_mult
        self._trades[trade_id]["ended_at"] = datetime.now(timezone.utc).isoformat()
        if is_simulation_mode(trade.get("mode")):
            self._apply_net_pnl_to_capital(net_pnl)
        if self.table:
            self.table.update_item(
                Key={"trade_id": trade_id},
                UpdateExpression="SET #s=:s, close_reason=:r, close_reason_text=:rt, exit_price=:e, ended_at=:t, gross_pnl_usd=:g, commission_usd=:c, net_pnl_usd=:n, rr_ratio=:rr, rr_planned=:rrp, rr_actual=:rra, r_multiple=:rm",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "CLOSED",
                    ":r": close_reason,
                    ":rt": reason_text,
                    ":e": _to_dynamodb_types(exit_price),
                    ":t": self._trades[trade_id]["ended_at"],
                    ":g": _to_dynamodb_types(gross_pnl),
                    ":c": _to_dynamodb_types(commission),
                    ":n": _to_dynamodb_types(net_pnl),
                    ":rr": _to_dynamodb_types(planned_rr),
                    ":rrp": _to_dynamodb_types(planned_rr),
                    ":rra": _to_dynamodb_types(r_mult),
                    ":rm": _to_dynamodb_types(r_mult),
                },
            )
        self._invalidate_trade_list_cache()
        if is_simulation_mode(trade.get("mode")) and trade.get("pair"):
            try:
                from src.core.pairs_manager import PairsManager

                PairsManager().increment_sim_stats_after_close(
                    str(trade["pair"]),
                    float(net_pnl),
                    risk_usd,
                )
            except Exception:
                logger.exception("increment_sim_stats_after_close failed")

    def _apply_net_pnl_to_capital(self, net_pnl: float) -> None:
        if not self.config_table:
            return
        item = self.config_table.get_item(Key={"key": "capital_total"}).get("Item")
        current = Decimal(str(item.get("value", 1183.0))) if item else Decimal("1183.0")
        updated = current + Decimal(str(net_pnl))
        self.config_table.put_item(Item={"key": "capital_total", "value": updated})

    def get_open_sims(self) -> list[dict]:
        return [
            t
            for t in self.list_trades()
            if is_simulation_mode(t.get("mode")) and t.get("status") == "OPEN"
        ]

    def get_open_live_trades(self) -> list[dict]:
        """live_test y live: open trades que requieren monitor de TP/SL y venta SPOT."""
        return [
            t
            for t in self.list_trades()
            if is_live_mode(t.get("mode")) and str(t.get("status", "")).upper() == "OPEN"
        ]

    def get_all_open_trades(self) -> list[dict]:
        return self.list_open(mode=MODE_SIMULATION)

    def list_open(self, mode: str | None = None) -> list[dict]:
        items = [t for t in self.list_trades() if t.get("status") == "OPEN"]
        if mode:
            target_mode = normalize_mode(mode)
            items = [t for t in items if normalize_mode(t.get("mode")) == target_mode]
        return sorted(items, key=lambda x: str(x.get("started_at", "")), reverse=True)

    def list_recent_closed(self, limit: int = 20, mode: str | None = None) -> list[dict]:
        from src.core.accounting import get_accounting_epoch_iso, trade_in_accounting_window

        epoch = get_accounting_epoch_iso()
        items = [
            t
            for t in self.list_trades()
            if t.get("status") == "CLOSED" and trade_in_accounting_window(t, epoch)
        ]
        if mode:
            target_mode = normalize_mode(mode)
            items = [t for t in items if normalize_mode(t.get("mode")) == target_mode]
        items = sorted(items, key=lambda x: str(x.get("ended_at", "")), reverse=True)
        return items[:limit]

    def _scan_table_segments(self, total_segments: int) -> list[dict]:
        """Scan completo usando Segment/TotalSegments en paralelo (menos tiempo con tablas grandes)."""
        tbl = self.table
        if tbl is None:
            return []

        def segment_items(seg: int) -> list[dict]:
            acc: list[dict] = []
            kwargs: dict = {"Segment": seg, "TotalSegments": total_segments}
            while True:
                resp = tbl.scan(**kwargs)
                acc.extend(resp.get("Items") or [])
                lek = resp.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs = {"Segment": seg, "TotalSegments": total_segments, "ExclusiveStartKey": lek}
            return acc

        if total_segments <= 1:
            return segment_items(0)

        with ThreadPoolExecutor(max_workers=total_segments) as ex:
            parts = list(ex.map(segment_items, range(total_segments)))
        return [row for part in parts for row in part]

    def list_trades(self) -> list[dict]:
        if self._list_cache is not None:
            return self._list_cache
        if not self.table:
            self._list_cache = list(self._trades.values())
            return self._list_cache
        segments = max(1, min(16, int(os.getenv("TRADES_SCAN_SEGMENTS", "8") or "8")))
        self._list_cache = self._scan_table_segments(segments)
        return self._list_cache

    def get_summary(self, mode: str | None = None) -> dict:
        """
        Cerradas: cohorte post accounting_epoch (si config). Abiertas: siempre.
        Si se informa mode, filtra abiertas y cerradas a ese modo.
        """
        from src.core.accounting import get_accounting_epoch_iso, trade_in_accounting_window

        epoch = get_accounting_epoch_iso()
        all_t = self.list_trades()
        target_mode = normalize_mode(mode) if mode else None
        opens = [t for t in all_t if t.get("status") == "OPEN"]
        closed = [
            t for t in all_t if t.get("status") == "CLOSED" and trade_in_accounting_window(t, epoch)
        ]
        if target_mode:
            opens = [t for t in opens if normalize_mode(t.get("mode")) == target_mode]
            closed = [t for t in closed if normalize_mode(t.get("mode")) == target_mode]
        items = opens + closed
        total = len(items)
        wins = len([t for t in closed if float(t.get("net_pnl_usd", 0) or 0) > 0])
        net = sum(float(t.get("net_pnl_usd", 0) or 0) for t in closed)
        by_mode = {
            "live": len([t for t in items if normalize_mode(t.get("mode")) == "live"]),
            "live_test": len([t for t in items if normalize_mode(t.get("mode")) == "live_test"]),
            "simulation": len(
                [t for t in items if normalize_mode(t.get("mode")) == MODE_SIMULATION]
            ),
        }
        return {
            "total": total,
            "open_count": len(opens),
            "closed": len(closed),
            "wins": wins,
            "net_pnl": net,
            "by_mode": by_mode,
        }

    def find_open_real_by_pair(self, pair: str) -> dict | None:
        normalized = pair.upper().strip()
        for t in self.list_open(mode="live"):
            if str(t.get("pair", "")).upper() == normalized:
                return t
        for t in self.list_open(mode="live_test"):
            if str(t.get("pair", "")).upper() == normalized:
                return t
        return None

    def can_open_live_trade(self, pair: str) -> tuple[bool, str]:
        """
        live/live_test: max N posiciones abiertas (default 1) y como mucho una por par.
        """
        max_n = int(settings.max_concurrent_live_open)
        opens = self.get_open_live_trades()
        if len(opens) >= max_n:
            busy = ", ".join(
                f"{t.get('pair')}({t.get('trade_id', '')[:8]})" for t in opens[:3]
            )
            return (
                False,
                f"max_concurrent_live_open={max_n} (abiertas: {busy})",
            )
        if self.find_open_real_by_pair(pair):
            return False, f"ya_hay_operacion_abierta_en_{pair}"
        return True, ""


def _to_dynamodb_types(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamodb_types(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamodb_types(v) for v in value]
    return value


def _close_reason_to_text(reason: str) -> str:
    normalized = str(reason or "").upper().strip()
    mapping = {
        "SL": "Stop loss alcanzado",
        "TP1": "Take profit 1 alcanzado",
        "TP2": "Take profit 2 alcanzado",
        "TP3": "Take profit 3 alcanzado",
        "TRAILING_SL": "Trailing stop activado y ejecutado",
        "MANUAL": "Cierre manual confirmado",
        "INVALID": "Operacion cerrada por estado inconsistente",
    }
    if normalized.startswith("SL_TP") and len(normalized) > 5:
        n = normalized[5:]
        return f"Retroceso al piso TP{n} (ganancia asegurada en escalera)"
    return mapping.get(normalized, f"Cierre por {normalized or 'motivo no informado'}")
