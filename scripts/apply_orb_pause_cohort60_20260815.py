#!/usr/bin/env python3
"""
Cohorte 60 (2026-08-15): correcciones postmortem 9 ops / -23.56.

- Quitar ORB de auto_trade_strategies; dejar RangeBreakout (si existe en strategies).
- Pares activos solo-ORB sin RB: se pausan (sin senal live).
- Reset accounting_epoch + capital_inicial a USDT wallet (o capital_total).
- Marca cohort_target_closes=60 en config.

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    PAIRS_TABLE_NAME=crypto-trading-bot-pairs CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/apply_orb_pause_cohort60_20260815.py

  --dry-run
  --no-reset
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import boto3

from src.core.config_store import ConfigStore
from src.core.pairs_manager import PairsManager

MATRIX_NOTE = (
    "2026-08-15: cohort60 — pause ORB auto_trade, RB only, TIME_STOP 3h/early 2h, "
    "BTC bullish alts, RB vol 1.5x; target 60 closes"
)
PAUSE_NO_RB = "Cohorte60: solo tenia ORB en auto y sin RangeBreakout"


def scan_all_pairs(table) -> list[dict]:
    items: list[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def strip_orb_keep_rb(current_auto: list[str], strategies: list[str]) -> list[str]:
    """Quita ORB; asegura RangeBreakout si esta en strategies."""
    s = set(strategies)
    kept = [x for x in current_auto if x != "ORB" and x in s]
    if "RangeBreakout" in s and "RangeBreakout" not in kept:
        # Preferir RB al frente si el par sigue en live.
        kept = ["RangeBreakout"] + [x for x in kept if x != "RangeBreakout"]
    # Dedup preserve order
    out: list[str] = []
    for x in kept:
        if x not in out:
            out.append(x)
    return out


def resolve_baseline_capital(store: ConfigStore) -> float:
    """Preferir USDT total de Binance; fallback a capital_total config."""
    try:
        from src.core.capital import get_capital_snapshot

        snap = get_capital_snapshot().as_dict()
        ctx = str(snap.get("capital_context") or "")
        total = float(snap.get("capital_total") or 0)
        if ctx.startswith("live") and total > 0:
            return total
    except Exception as exc:  # noqa: BLE001
        print(f"WARN capital snapshot: {exc}", file=sys.stderr)
    cap = float(store.get_capital(0.0) or 0.0)
    if cap <= 0:
        cap = float(store.get_number("capital_inicial_live_test", 0.0) or 0.0)
    return cap


def reset_accounting(dry_run: bool) -> None:
    store = ConfigStore()
    capital_now = resolve_baseline_capital(store)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if dry_run:
        print(f"[DRY] accounting_epoch_started_at = {now}")
        print(f"[DRY] capital_inicial_live_test = {capital_now:.8f}")
        print(f"[DRY] capital_inicial = {capital_now:.8f}")
        print(f"[DRY] capital_total = {capital_now:.8f}")
        print("[DRY] cohort_target_closes = 60")
        return
    store.set_str("accounting_epoch_started_at", now)
    store.set_number("capital_inicial_live_test", capital_now)
    store.set_number("capital_inicial", capital_now)
    store.set_capital(capital_now)
    store.set_number("cohort_target_closes", 60)
    store.set_str("strategy_matrix_last_update", MATRIX_NOTE)
    print(f"accounting_epoch_started_at = {now}")
    print(f"capital_inicial_live_test = {capital_now:.8f}")
    print(f"capital_inicial = {capital_now:.8f}")
    print(f"capital_total = {capital_now:.8f}")
    print("cohort_target_closes = 60")
    print("PnL contable reseteado (cohorte hasta 60 cierres).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-reset", action="store_true")
    args = ap.parse_args()

    table_name = os.getenv("PAIRS_TABLE_NAME", "crypto-trading-bot-pairs")
    table = boto3.resource("dynamodb").Table(table_name)
    pm = PairsManager()
    items = scan_all_pairs(table)

    auto_updates = 0
    paused = 0
    orb_removed = 0

    for item in sorted(items, key=lambda x: str(x.get("pair", ""))):
        pair = str(item.get("pair", "")).upper().strip()
        if not pair:
            continue
        current_strat = [str(x) for x in item.get("strategies", [])]
        current_auto = [str(x) for x in item.get("auto_trade_strategies", [])]
        active = bool(item.get("active", True))
        had_orb = "ORB" in current_auto
        new_auto = strip_orb_keep_rb(current_auto, current_strat)

        if had_orb:
            orb_removed += 1

        if active and not new_auto:
            # Activo pero sin estrategia live residual → pausar.
            if args.dry_run:
                print(f"[DRY] pausar {pair} (sin RB tras quitar ORB; auto era {current_auto})")
            else:
                if pm.set_pair_active(pair, False, PAUSE_NO_RB):
                    paused += 1
                    print(f"pausado {pair} (sin RangeBreakout)")
            if new_auto != current_auto:
                if args.dry_run:
                    print(f"[DRY] {pair} auto_trade_strategies: {current_auto} -> {new_auto}")
                else:
                    table.update_item(
                        Key={"pair": pair},
                        UpdateExpression="SET auto_trade_strategies = :a",
                        ExpressionAttributeValues={":a": new_auto},
                    )
                auto_updates += 1
            continue

        if new_auto != current_auto:
            if args.dry_run:
                print(f"[DRY] {pair} auto_trade_strategies: {current_auto} -> {new_auto}")
            else:
                table.update_item(
                    Key={"pair": pair},
                    UpdateExpression="SET auto_trade_strategies = :a",
                    ExpressionAttributeValues={":a": new_auto},
                )
                print(f"{pair}: auto {current_auto} -> {new_auto}")
            auto_updates += 1

    print(
        f"\nResumen: pairs={len(items)} auto_updated={auto_updates} "
        f"orb_seen={orb_removed} newly_paused={paused}"
    )

    if not args.no_reset:
        print("\n=== Reset contable cohorte 60 ===")
        reset_accounting(args.dry_run)
    elif not args.dry_run:
        ConfigStore().set_str("strategy_matrix_last_update", MATRIX_NOTE)
        ConfigStore().set_number("cohort_target_closes", 60)

    if not args.dry_run:
        active_n = len(pm.get_active_pairs())
        print(f"\nActivos ahora: {active_n}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
