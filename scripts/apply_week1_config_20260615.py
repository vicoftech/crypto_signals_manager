#!/usr/bin/env python3
"""
Semana 1 (2026-06-15): matriz conservadora + auto_trade ORB/RB + pausar pares debiles.

1. Quitar EMAPullback de 10 pares con peor rendimiento live (cohorte post-reset).
2. auto_trade_strategies = ORB + RangeBreakout en pares con auto_trade.
3. Pausar AVAX, THETA, GRT, DOGE, ADA.

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    PAIRS_TABLE_NAME=crypto-trading-bot-pairs CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/apply_week1_config_20260615.py

  --dry-run para solo imprimir cambios.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import boto3

from src.core.pairs_manager import PairsManager

# Cohorte live_test post-reset: EMAPullback WR <=33% y PnL negativo (n>=2).
REMOVE_EMA_PAIRS = {
    "AVAXUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "THETAUSDT",
    "SEIUSDT",
    "BCHUSDT",
    "TIAUSDT",
    "CRVUSDT",
    "SANDUSDT",
    "NEARUSDT",
}

PAUSE_PAIRS = {
    "AVAXUSDT",
    "THETAUSDT",
    "GRTUSDT",
    "DOGEUSDT",
    "ADAUSDT",
}

PAUSE_REASON = "Semana 1: WR live bajo en cohorte post-reset (2026-06-15)"

KEEP_ORDER = ["RangeBreakout", "SupportBounce", "ORB", "EMAPullback", "MACDCross", "Momentum"]
AUTO_TRADE_PREFERRED = ["ORB", "RangeBreakout"]
MATRIX_NOTE = "2026-06-15: week1 — remove EMA weak pairs, auto_trade ORB+RB, pause 5 pairs"


def ordered_unique(values: list[str]) -> list[str]:
    s = {str(v) for v in values}
    return [x for x in KEEP_ORDER if x in s]


def compute_auto_trade_strategies(strategies: list[str]) -> list[str]:
    s = set(strategies)
    picked = [x for x in AUTO_TRADE_PREFERRED if x in s]
    return picked if picked else ordered_unique([x for x in strategies if x in AUTO_TRADE_PREFERRED])


def scan_all_pairs(table) -> list[dict]:
    items: list[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    table_name = os.getenv("PAIRS_TABLE_NAME", "crypto-trading-bot-pairs")
    if not table_name:
        print("PAIRS_TABLE_NAME requerido.", file=sys.stderr)
        return 1

    table = boto3.resource("dynamodb").Table(table_name)
    pm = PairsManager()
    items = scan_all_pairs(table)

    strat_updates = 0
    auto_updates = 0
    paused = 0

    for item in sorted(items, key=lambda x: str(x.get("pair", ""))):
        pair = str(item.get("pair", "")).upper().strip()
        if not pair:
            continue

        current_strat = [str(x) for x in item.get("strategies", [])]
        new_strat = current_strat
        if pair in REMOVE_EMA_PAIRS:
            new_strat = ordered_unique([s for s in current_strat if s != "EMAPullback"])
            if not new_strat:
                new_strat = ["RangeBreakout", "SupportBounce", "ORB"]

        current_auto = [str(x) for x in item.get("auto_trade_strategies", [])]
        auto_trade = bool(item.get("auto_trade", False))
        new_auto = current_auto
        if auto_trade:
            new_auto = compute_auto_trade_strategies(new_strat)

        strat_changed = new_strat != current_strat
        auto_changed = new_auto != current_auto

        if strat_changed or auto_changed:
            if args.dry_run:
                if strat_changed:
                    print(f"[DRY] {pair} strategies: {current_strat} -> {new_strat}")
                if auto_changed:
                    print(f"[DRY] {pair} auto_trade_strategies: {current_auto} -> {new_auto}")
            else:
                expr_parts = []
                vals: dict = {}
                if strat_changed:
                    expr_parts.append("strategies = :s")
                    vals[":s"] = new_strat
                    strat_updates += 1
                if auto_changed:
                    expr_parts.append("auto_trade_strategies = :a")
                    vals[":a"] = new_auto
                    auto_updates += 1
                table.update_item(
                    Key={"pair": pair},
                    UpdateExpression="SET " + ", ".join(expr_parts),
                    ExpressionAttributeValues=vals,
                )
                print(
                    f"{pair}: "
                    + (f"strategies {current_strat} -> {new_strat}; " if strat_changed else "")
                    + (f"auto {current_auto} -> {new_auto}" if auto_changed else "")
                )

        if pair in PAUSE_PAIRS and bool(item.get("active", True)):
            if args.dry_run:
                print(f"[DRY] pausar {pair}")
            else:
                if pm.set_pair_active(pair, False, PAUSE_REASON):
                    paused += 1
                    print(f"pausado {pair}")
                else:
                    print(f"FAIL pausar {pair}", file=sys.stderr)

    if not args.dry_run:
        cfg_table_name = os.getenv("CONFIG_TABLE_NAME", "crypto-trading-bot-config")
        if cfg_table_name:
            boto3.resource("dynamodb").Table(cfg_table_name).put_item(
                Item={
                    "key": "strategy_matrix_last_update",
                    "value": MATRIX_NOTE,
                }
            )

    print(
        f"\nResumen: pairs={len(items)} "
        f"strategies_updated={strat_updates} auto_trade_updated={auto_updates} paused={paused}"
    )
    if not args.dry_run:
        active_n = len(pm.get_active_pairs())
        print(f"Activos ahora: {active_n}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
