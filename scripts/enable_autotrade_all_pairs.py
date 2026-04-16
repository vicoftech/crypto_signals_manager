#!/usr/bin/env python3
"""Marca todos los pares en PairsTable con auto_trade=true.

auto_trade_strategies se rellena con la lista `strategies` de cada item (preserva sim_stats).
Ejecutar desde la raíz del repo con credenciales AWS (p. ej. AWS_PROFILE=asap_main).
"""
from __future__ import annotations

import os
import sys

import boto3


def main() -> int:
    table_name = os.environ.get("PAIRS_TABLE_NAME", "crypto-trading-bot-pairs")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    updated = 0
    scan_kwargs: dict = {}
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            pair = item.get("pair")
            if not pair:
                continue
            strategies = list(item.get("strategies") or [])
            table.update_item(
                Key={"pair": pair},
                UpdateExpression="SET auto_trade = :at, auto_trade_strategies = :ats",
                ExpressionAttributeValues={
                    ":at": True,
                    ":ats": strategies,
                },
            )
            updated += 1
            print(pair, "auto_trade=True", "n_strats=", len(strategies))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        scan_kwargs["ExclusiveStartKey"] = lek
    print("OK updated", updated, "pairs in", table_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
