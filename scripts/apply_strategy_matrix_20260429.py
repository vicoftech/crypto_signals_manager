#!/usr/bin/env python3
from __future__ import annotations

"""
Aplica una matriz conservadora de estrategias por par en la tabla de pairs.

Razon:
- Ultimas 243 operaciones: expectativa negativa y mayor drenaje desde EMAPullback.
- Pares debiles (SUI, FIL, XLM, SOL, DOT) con bajo winrate y PnL negativo.

Accion:
- En pares debiles, quitar EMAPullback y MACDCross.
- Si un par no tiene ORB, se conserva con RangeBreakout + SupportBounce.
"""

import os
from decimal import Decimal

import boto3


WEAK_PAIRS = {"SUIUSDT", "FILUSDT", "XLMUSDT", "SOLUSDT", "DOTUSDT"}
KEEP_ORDER = ["RangeBreakout", "SupportBounce", "ORB", "EMAPullback", "MACDCross", "Momentum"]


def ordered_unique(values: list[str]) -> list[str]:
    s = {str(v) for v in values}
    return [x for x in KEEP_ORDER if x in s]


def main() -> int:
    table_name = os.getenv("PAIRS_TABLE_NAME", "crypto-trading-bot-pairs")
    table = boto3.resource("dynamodb").Table(table_name)
    resp = table.scan()
    items = list(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))

    updates = 0
    for item in items:
        pair = str(item.get("pair", "")).upper().strip()
        if pair not in WEAK_PAIRS:
            continue
        current = [str(x) for x in item.get("strategies", [])]
        # Remove weak performers in these pairs.
        new = [s for s in current if s not in {"EMAPullback", "MACDCross"}]
        new = ordered_unique(new)
        if not new:
            new = ["RangeBreakout", "SupportBounce"]
        if new == current:
            continue
        table.update_item(
            Key={"pair": pair},
            UpdateExpression="SET strategies = :s",
            ExpressionAttributeValues={":s": [str(x) for x in new]},
        )
        updates += 1
        print(f"{pair}: {current} -> {new}")

    cfg_table = boto3.resource("dynamodb").Table(os.getenv("CONFIG_TABLE_NAME", "crypto-trading-bot-config"))
    cfg_table.put_item(
        Item={
            "key": "strategy_matrix_last_update",
            "value": "2026-04-29: weak pairs remove EMAPullback/MACDCross (243-trade review)",
        }
    )
    print(f"Pairs updated: {updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
