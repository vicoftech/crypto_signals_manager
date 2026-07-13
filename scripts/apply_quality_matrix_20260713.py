#!/usr/bin/env python3
"""
Matriz de calidad (2026-07-13) + reset contable a cero.

Basado en analisis de ultimas 105 live_test:
- Pausar pares con WR bajo / PnL negativo.
- auto_trade_strategies acotado por par (ORB y/o RangeBreakout).
- Whitelist corta de live; el resto pausado.
- Reset accounting_epoch + capital_inicial_live_test = capital actual (PnL 0).

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    PAIRS_TABLE_NAME=crypto-trading-bot-pairs CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/apply_quality_matrix_20260713.py

  --dry-run  solo imprime
  --no-reset  aplica matriz sin resetear contadores
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import boto3

from src.core.config_store import ConfigStore
from src.core.pairs_manager import PairsManager

PAUSE_REASON = "Calidad 2026-07-13: WR/PnL live bajo o fuera de whitelist"

# Pares que quedan activos para live (resto se pausa).
KEEP_ACTIVE = {
    "AAVEUSDT",
    "ALGOUSDT",
    "APTUSDT",
    "BCHUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "DOTUSDT",
    "ETCUSDT",
    "ETHUSDT",
    "FILUSDT",
    "ICPUSDT",
    "LDOUSDT",
    "LTCUSDT",
    "MANAUSDT",
    "NEARUSDT",
    "OPUSDT",
    "RUNEUSDT",
    "SNXUSDT",
    "SUIUSDT",
    "UNIUSDT",
    "VETUSDT",
    "XLMUSDT",
}

# auto_trade_strategies por par (solo los listados; filtrados a lo que exista en strategies).
AUTO_BY_PAIR: dict[str, list[str]] = {
    "AAVEUSDT": ["RangeBreakout"],
    "ALGOUSDT": ["RangeBreakout"],
    "APTUSDT": ["ORB", "RangeBreakout"],
    "BCHUSDT": ["ORB"],
    "BNBUSDT": ["ORB"],
    "BTCUSDT": ["ORB", "RangeBreakout"],
    "DOTUSDT": ["ORB"],
    "ETCUSDT": ["ORB"],
    "ETHUSDT": ["RangeBreakout"],
    "FILUSDT": ["ORB", "RangeBreakout"],
    "ICPUSDT": ["ORB", "RangeBreakout"],
    "LDOUSDT": ["RangeBreakout"],
    "LTCUSDT": ["ORB"],
    "MANAUSDT": ["RangeBreakout"],
    "NEARUSDT": ["ORB", "RangeBreakout"],
    "OPUSDT": ["RangeBreakout"],
    "RUNEUSDT": ["RangeBreakout"],
    "SNXUSDT": ["RangeBreakout"],
    "SUIUSDT": ["ORB"],
    "UNIUSDT": ["ORB"],
    "VETUSDT": ["RangeBreakout"],
    "XLMUSDT": ["ORB"],
}

MATRIX_NOTE = (
    "2026-07-13: quality matrix — whitelist live, ORB/RB por par, pause underperformers, "
    "accounting reset"
)


def scan_all_pairs(table) -> list[dict]:
    items: list[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def filter_auto(wanted: list[str], strategies: list[str]) -> list[str]:
    s = set(strategies)
    return [x for x in wanted if x in s]


def reset_accounting(dry_run: bool) -> None:
    store = ConfigStore()
    # Linea base = capital_total actual en config (fallback live); PnL queda en 0.
    capital_now = store.get_capital(store.get_number("capital_inicial_live_test", 0.0))
    if capital_now <= 0:
        capital_now = store.get_number("capital_inicial_live_test", 0.0)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if dry_run:
        print(f"[DRY] accounting_epoch_started_at = {now}")
        print(f"[DRY] capital_inicial_live_test = {capital_now:.8f}")
        print(f"[DRY] capital_inicial = {capital_now:.8f}")
        print(f"[DRY] capital_total = {capital_now:.8f}")
        return
    store.set_str("accounting_epoch_started_at", now)
    store.set_number("capital_inicial_live_test", capital_now)
    store.set_number("capital_inicial", capital_now)
    store.set_capital(capital_now)
    store.set_str("strategy_matrix_last_update", MATRIX_NOTE)
    print(f"accounting_epoch_started_at = {now}")
    print(f"capital_inicial_live_test = {capital_now:.8f}")
    print(f"capital_inicial = {capital_now:.8f}")
    print(f"capital_total = {capital_now:.8f}")
    print("PnL contable reseteado a ~0 (cohorte nueva).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-reset", action="store_true", help="No resetear epoch/capital")
    args = ap.parse_args()

    table_name = os.getenv("PAIRS_TABLE_NAME", "crypto-trading-bot-pairs")
    if not table_name:
        print("PAIRS_TABLE_NAME requerido.", file=sys.stderr)
        return 1

    table = boto3.resource("dynamodb").Table(table_name)
    pm = PairsManager()
    items = scan_all_pairs(table)

    auto_updates = 0
    paused = 0
    already_paused = 0
    kept = 0

    for item in sorted(items, key=lambda x: str(x.get("pair", ""))):
        pair = str(item.get("pair", "")).upper().strip()
        if not pair:
            continue
        current_strat = [str(x) for x in item.get("strategies", [])]
        current_auto = [str(x) for x in item.get("auto_trade_strategies", [])]
        active = bool(item.get("active", True))

        if pair in KEEP_ACTIVE:
            wanted = AUTO_BY_PAIR.get(pair, ["ORB", "RangeBreakout"])
            new_auto = filter_auto(wanted, current_strat)
            if not new_auto:
                # Si ORB no esta en strategies pero lo pedimos, no inventar; caer a RB si existe.
                new_auto = filter_auto(["RangeBreakout", "ORB"], current_strat)
            if not new_auto:
                print(f"WARN {pair}: sin ORB/RB en strategies={current_strat}", file=sys.stderr)
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

            if not active:
                if args.dry_run:
                    print(f"[DRY] activar {pair} (whitelist)")
                else:
                    pm.set_pair_active(pair, True, "Calidad 2026-07-13: whitelist live")
                    print(f"activado {pair}")
            kept += 1
        else:
            if active:
                if args.dry_run:
                    print(f"[DRY] pausar {pair}")
                else:
                    if pm.set_pair_active(pair, False, PAUSE_REASON):
                        paused += 1
                        print(f"pausado {pair}")
                    else:
                        print(f"FAIL pausar {pair}", file=sys.stderr)
            else:
                already_paused += 1

    print(
        f"\nResumen matriz: pairs={len(items)} kept_active={kept} "
        f"auto_updated={auto_updates} newly_paused={paused} already_paused={already_paused}"
    )

    if not args.no_reset:
        print("\n=== Reset contable ===")
        reset_accounting(args.dry_run)
    elif not args.dry_run:
        ConfigStore().set_str("strategy_matrix_last_update", MATRIX_NOTE)

    if not args.dry_run:
        active_n = len(pm.get_active_pairs())
        print(f"\nActivos ahora: {active_n}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
