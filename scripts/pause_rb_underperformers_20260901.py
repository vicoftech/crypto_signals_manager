#!/usr/bin/env python3
"""
Pausa pares RangeBreakout con peor rendimiento cohorte 56 ops (2026-09-01).

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    PAIRS_TABLE_NAME=crypto-trading-bot-pairs CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/pause_rb_underperformers_20260901.py

  --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

from src.core.config_store import ConfigStore
from src.core.pairs_manager import PairsManager

PAUSE_PAIRS = ("LDOUSDT", "UNIUSDT", "SNXUSDT", "BNBUSDT")

REASONS = {
    "LDOUSDT": "RB cohorte56: 0/5 WR, MFE~0 — sin impulso post-breakout",
    "UNIUSDT": "RB cohorte56: 0/3 WR — falsos breakouts",
    "SNXUSDT": "RB cohorte56: 0/3 neto — ops muertas + escalera",
    "BNBUSDT": "RB cohorte56: 0/2 WR — cero follow-through",
}

MATRIX_NOTE = "2026-09-01: pause LDO UNI SNX BNB — RB underperformers cohorte 56"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.getenv("PAIRS_TABLE_NAME"):
        print("PAIRS_TABLE_NAME requerido.", file=sys.stderr)
        return 1

    pm = PairsManager()
    paused = 0
    for pair in PAUSE_PAIRS:
        reason = REASONS.get(pair, "RB underperformer cohorte 56")
        if args.dry_run:
            print(f"[DRY] pausar {pair}: {reason}")
            continue
        if pm.set_pair_active(pair, False, reason):
            print(f"pausado {pair}")
            paused += 1
        else:
            print(f"FAIL pausar {pair}", file=sys.stderr)

    if not args.dry_run:
        ConfigStore().set_str("strategy_matrix_last_update", MATRIX_NOTE)
        print(f"\nActivos ahora: {len(pm.get_active_pairs())}")
        print(f"Pausados: {paused}/{len(PAUSE_PAIRS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
