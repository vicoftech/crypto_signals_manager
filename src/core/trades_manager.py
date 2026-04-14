from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import boto3

from src.core.market_session import format_market_session


class TradesManager:
    def __init__(self) -> None:
        self.table_name = os.getenv("TRADES_TABLE_NAME", "")
        self.config_table_name = os.getenv("CONFIG_TABLE_NAME", "")
        self.table = boto3.resource("dynamodb").Table(self.table_name) if self.table_name else None
        self.config_table = boto3.resource("dynamodb").Table(self.config_table_name) if self.config_table_name else None
        self._trades: dict[str, dict] = {}

    def open_trade(self, payload: dict, mode: str) -> str:
        trade_id = str(uuid4())
        started = datetime.now(timezone.utc)
        row = {
            "trade_id": trade_id,
            "mode": mode,
            "status": "OPEN",
            "started_at": started.isoformat(),
            "market_session": format_market_session(started),
            **payload,
        }
        if self.table:
            self.table.put_item(Item=_to_dynamodb_types(row))
        self._trades[trade_id] = row
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
        commission = size * 0.002
        net_pnl = gross_pnl - commission
        reason_text = _close_reason_to_text(close_reason)
        self._trades[trade_id]["status"] = "CLOSED"
        self._trades[trade_id]["close_reason"] = close_reason
        self._trades[trade_id]["close_reason_text"] = reason_text
        self._trades[trade_id]["exit_price"] = exit_price
        self._trades[trade_id]["gross_pnl_usd"] = gross_pnl
        self._trades[trade_id]["commission_usd"] = commission
        self._trades[trade_id]["net_pnl_usd"] = net_pnl
        self._trades[trade_id]["ended_at"] = datetime.now(timezone.utc).isoformat()
        self._apply_net_pnl_to_capital(net_pnl)
        if self.table:
            self.table.update_item(
                Key={"trade_id": trade_id},
                UpdateExpression="SET #s=:s, close_reason=:r, close_reason_text=:rt, exit_price=:e, ended_at=:t, gross_pnl_usd=:g, commission_usd=:c, net_pnl_usd=:n",
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
                },
            )

    def _apply_net_pnl_to_capital(self, net_pnl: float) -> None:
        if not self.config_table:
            return
        item = self.config_table.get_item(Key={"key": "capital_total"}).get("Item")
        current = Decimal(str(item.get("value", 1183.0))) if item else Decimal("1183.0")
        updated = current + Decimal(str(net_pnl))
        self.config_table.put_item(Item={"key": "capital_total", "value": updated})

    def get_open_sims(self) -> list[dict]:
        return [t for t in self.list_trades() if t.get("mode") == "SIM" and t.get("status") == "OPEN"]

    def list_open(self, mode: str | None = None) -> list[dict]:
        items = [t for t in self.list_trades() if t.get("status") == "OPEN"]
        if mode:
            items = [t for t in items if t.get("mode") == mode]
        return sorted(items, key=lambda x: str(x.get("started_at", "")), reverse=True)

    def list_recent_closed(self, limit: int = 20) -> list[dict]:
        items = [t for t in self.list_trades() if t.get("status") == "CLOSED"]
        items = sorted(items, key=lambda x: str(x.get("ended_at", "")), reverse=True)
        return items[:limit]

    def list_trades(self) -> list[dict]:
        if self.table:
            return self.table.scan().get("Items", [])
        return list(self._trades.values())

    def get_summary(self) -> dict:
        items = self.list_trades()
        closed = [t for t in items if t.get("status") == "CLOSED"]
        total = len(items)
        wins = len([t for t in closed if float(t.get("net_pnl_usd", 0) or 0) > 0])
        net = sum(float(t.get("net_pnl_usd", 0) or 0) for t in closed)
        by_mode = {
            "REAL": len([t for t in items if t.get("mode") == "REAL"]),
            "SIM": len([t for t in items if t.get("mode") == "SIM"]),
        }
        return {"total": total, "closed": len(closed), "wins": wins, "net_pnl": net, "by_mode": by_mode}

    def find_open_real_by_pair(self, pair: str) -> dict | None:
        normalized = pair.upper().strip()
        for t in self.list_open(mode="REAL"):
            if str(t.get("pair", "")).upper() == normalized:
                return t
        return None


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
        "TRAILING_SL": "Trailing stop activado y ejecutado",
        "MANUAL": "Cierre manual confirmado",
        "INVALID": "Operacion cerrada por estado inconsistente",
    }
    return mapping.get(normalized, f"Cierre por {normalized or 'motivo no informado'}")
