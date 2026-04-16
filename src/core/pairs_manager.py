from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from src.core.auto_sim_utils import check_auto_trade_eligibility, default_sim_stats


@dataclass
class PairConfig:
    pair: str
    active: bool
    tier: str
    strategies: list[str]
    sim_mode: str = "manual"
    auto_trade: bool = False
    auto_trade_strategies: list[str] = field(default_factory=list)
    sim_auto_enabled_at: str | None = None
    sim_auto_reason: str | None = None
    sim_stats: dict | None = None


class PairsManager:
    def __init__(self) -> None:
        self.table_name = os.getenv("PAIRS_TABLE_NAME", "")
        self._pairs: list[PairConfig] = []

    def get_active_pairs(self) -> list[PairConfig]:
        return [p for p in self.get_all_pairs() if p.active]

    def _item_to_config(self, i: dict) -> PairConfig:
        stats = i.get("sim_stats")
        if stats and isinstance(stats, dict):
            stats = {
                k: float(v) if k in ("pnl_total_usd", "r_multiple_avg") else int(v)
                if k in ("total_sim", "ganadoras", "perdedoras")
                else (str(v) if k == "last_updated" else v)
                for k, v in stats.items()
            }
        return PairConfig(
            pair=i["pair"],
            active=bool(i.get("active", True)),
            tier=str(i.get("tier", "1")),
            strategies=list(i.get("strategies", [])),
            sim_mode=str(i.get("sim_mode", "manual")),
            auto_trade=bool(i.get("auto_trade", False)),
            auto_trade_strategies=list(i.get("auto_trade_strategies", [])),
            sim_auto_enabled_at=i.get("sim_auto_enabled_at"),
            sim_auto_reason=i.get("sim_auto_reason"),
            sim_stats=dict(stats) if stats else None,
        )

    def get_all_pairs(self) -> list[PairConfig]:
        if self.table_name:
            table = boto3.resource("dynamodb").Table(self.table_name)
            items = table.scan().get("Items", [])
            return [self._item_to_config(i) for i in items]
        return self._pairs

    def add_pair(self, pair: str) -> None:
        normalized = pair.upper().strip()
        default_strategies = ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"]
        item = {
            "pair": normalized,
            "active": True,
            "tier": "1",
            "strategies": default_strategies,
            "sim_mode": "manual",
            "auto_trade": False,
            "auto_trade_strategies": [],
            "sim_stats": default_sim_stats(),
        }
        if self.table_name:
            table = boto3.resource("dynamodb").Table(self.table_name)
            table.put_item(Item=_ddb_map(item))
            return
        self._pairs.append(self._item_to_config(item))

    def set_active(self, pair: str, active: bool) -> bool:
        normalized = pair.upper().strip()
        if self.table_name:
            table = boto3.resource("dynamodb").Table(self.table_name)
            existing = table.get_item(Key={"pair": normalized}).get("Item")
            if not existing:
                return False
            table.update_item(
                Key={"pair": normalized},
                UpdateExpression="SET active = :a",
                ExpressionAttributeValues={":a": active},
            )
            return True
        for p in self._pairs:
            if p.pair == normalized:
                p.active = active
                return True
        return False

    def set_sim_mode(self, pair: str, mode: str) -> bool:
        normalized = pair.upper().strip()
        if mode not in ("manual", "auto", "disabled"):
            return False
        if self.table_name:
            table = boto3.resource("dynamodb").Table(self.table_name)
            existing = table.get_item(Key={"pair": normalized}).get("Item")
            if not existing:
                return False
            now = datetime.now(timezone.utc).isoformat()
            if mode == "auto":
                table.update_item(
                    Key={"pair": normalized},
                    UpdateExpression="SET sim_mode = :m, sim_auto_enabled_at = :t, sim_auto_reason = :r",
                    ExpressionAttributeValues={
                        ":m": mode,
                        ":t": now,
                        ":r": "Comando /simconfig",
                    },
                )
            else:
                table.update_item(
                    Key={"pair": normalized},
                    UpdateExpression="SET sim_mode = :m",
                    ExpressionAttributeValues={":m": mode},
                )
            return True
        for p in self._pairs:
            if p.pair == normalized:
                p.sim_mode = mode
                return True
        return False

    def get_pair(self, pair: str) -> PairConfig | None:
        normalized = pair.upper().strip()
        for p in self.get_all_pairs():
            if p.pair == normalized:
                return p
        return None

    def increment_sim_stats_after_close(self, pair: str, net_pnl_usd: float, risk_usd: float) -> None:
        if not self.table_name:
            return
        table = boto3.resource("dynamodb").Table(self.table_name)
        item = table.get_item(Key={"pair": pair.upper().strip()}).get("Item")
        if not item:
            return
        stats = item.get("sim_stats") or default_sim_stats()
        total = int(stats.get("total_sim", 0) or 0) + 1
        gan = int(stats.get("ganadoras", 0) or 0) + (1 if net_pnl_usd > 0 else 0)
        perd = int(stats.get("perdedoras", 0) or 0) + (1 if net_pnl_usd <= 0 else 0)
        pnl_tot = float(stats.get("pnl_total_usd", 0) or 0) + net_pnl_usd
        r_inst = (net_pnl_usd / risk_usd) if risk_usd and risk_usd > 0 else 0.0
        old_avg = float(stats.get("r_multiple_avg", 0) or 0)
        r_avg = old_avg + (r_inst - old_avg) / total if total > 0 else r_inst
        new_stats = {
            "total_sim": total,
            "ganadoras": gan,
            "perdedoras": perd,
            "pnl_total_usd": pnl_tot,
            "r_multiple_avg": r_avg,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        table.update_item(
            Key={"pair": pair.upper().strip()},
            UpdateExpression="SET sim_stats = :s",
            ExpressionAttributeValues={":s": _ddb_map(new_stats)},
        )

    def eligibility_for_pair(self, pair: str) -> dict:
        p = self.get_pair(pair)
        return check_auto_trade_eligibility(p.sim_stats if p else None)


def _ddb_map(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, float):
            out[k] = Decimal(str(v))
        elif isinstance(v, dict):
            out[k] = _ddb_map(v)
        else:
            out[k] = v
    return out
