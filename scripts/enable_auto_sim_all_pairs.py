#!/usr/bin/env python3
"""Pone sim_mode=auto en todos los pares de PairsTable (simulacion automatica sin botones).

Equivale a /simconfig <PAR> auto para cada par. No modifica auto_trade ni sim_stats.
Uso: AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 python3 scripts/enable_auto_sim_all_pairs.py
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3


def main() -> int:
    table_name = os.environ.get("PAIRS_TABLE_NAME", "crypto-trading-bot-pairs")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    reason = os.environ.get("SIM_AUTO_REASON", "Script masivo: todas las posiciones en auto-sim")
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    scan_kwargs: dict = {}
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            pair = item.get("pair")
            if not pair:
                continue
            table.update_item(
                Key={"pair": pair},
                UpdateExpression="SET sim_mode = :m, sim_auto_enabled_at = :t, sim_auto_reason = :r",
                ExpressionAttributeValues={
                    ":m": "auto",
                    ":t": now,
                    ":r": reason,
                },
            )
            updated += 1
            print(pair, "sim_mode=auto")
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        scan_kwargs["ExclusiveStartKey"] = lek
    print("OK updated", updated, "pairs in", table_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
