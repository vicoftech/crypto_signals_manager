from __future__ import annotations

import os
from decimal import Decimal

import boto3


class ConfigStore:
    def __init__(self) -> None:
        self.table_name = os.getenv("CONFIG_TABLE_NAME", "")
        self.table = boto3.resource("dynamodb").Table(self.table_name) if self.table_name else None

    def _get(self, key: str) -> dict:
        if not self.table:
            return {}
        return self.table.get_item(Key={"key": key}).get("Item", {})

    def _put(self, item: dict) -> None:
        if self.table:
            self.table.put_item(Item=item)

    def get_capital(self, default: float) -> float:
        val = self._get("capital_total").get("value")
        return float(val) if val is not None else default

    def set_capital(self, value: float) -> None:
        self._put({"key": "capital_total", "value": Decimal(str(value))})

    def get_risk_pct(self, default: float) -> float:
        val = self._get("risk_pct").get("value")
        return float(val) if val is not None else default

    def set_risk_pct(self, value: float) -> None:
        self._put({"key": "risk_pct", "value": Decimal(str(value))})

    def is_paused(self) -> bool:
        val = self._get("scanner_paused").get("value")
        return bool(val) if val is not None else False

    def set_paused(self, paused: bool) -> None:
        self._put({"key": "scanner_paused", "value": paused})

    def get_number(self, key: str, default: float = 0.0) -> float:
        val = self._get(key).get("value")
        return float(val) if val is not None else default

    def set_number(self, key: str, value: float) -> None:
        self._put({"key": key, "value": Decimal(str(value))})
