from __future__ import annotations

import os
from dataclasses import dataclass

import boto3


@dataclass
class PairConfig:
    pair: str
    active: bool
    tier: str
    strategies: list[str]


class PairsManager:
    def __init__(self) -> None:
        self.table_name = os.getenv("PAIRS_TABLE_NAME", "")
        self._pairs = []

    def get_active_pairs(self) -> list[PairConfig]:
        return [p for p in self.get_all_pairs() if p.active]

    def get_all_pairs(self) -> list[PairConfig]:
        if self.table_name:
            table = boto3.resource("dynamodb").Table(self.table_name)
            items = table.scan().get("Items", [])
            return [
                PairConfig(
                    pair=i["pair"],
                    active=bool(i.get("active", True)),
                    tier=str(i.get("tier", "1")),
                    strategies=list(i.get("strategies", [])),
                )
                for i in items
            ]
        return self._pairs

    def add_pair(self, pair: str) -> None:
        normalized = pair.upper().strip()
        default_strategies = ["EMAPullback", "RangeBreakout", "SupportBounce", "MACDCross", "ORB", "Momentum"]
        if self.table_name:
            table = boto3.resource("dynamodb").Table(self.table_name)
            table.put_item(
                Item={"pair": normalized, "active": True, "tier": "1", "strategies": default_strategies},
            )
            return
        self._pairs.append(PairConfig(pair=normalized, active=True, tier="1", strategies=default_strategies))

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

    def get_pair(self, pair: str) -> PairConfig | None:
        normalized = pair.upper().strip()
        for p in self.get_all_pairs():
            if p.pair == normalized:
                return p
        return None
