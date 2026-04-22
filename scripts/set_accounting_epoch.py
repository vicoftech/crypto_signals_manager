#!/usr/bin/env python3
from __future__ import annotations

"""
Escribe `accounting_epoch_started_at` en ConfigTable (ISO UTC).
Trades cerrados con ended_at anterior al corte quedan fuera de /resumen, /rendimiento, /historial.

Uso (corte a inicio de dia en UTC, ej. post-fix 16-abr-2026):
  CONFIG_TABLE_NAME=crypto-trading-bot-config PYTHONPATH=. \\
    python3 scripts/set_accounting_epoch.py 2026-04-17T00:00:00+00:00

Vaciar el corte (usar todo el historial en agregados):
  python3 scripts/set_accounting_epoch.py --clear
"""

import argparse

from src.core.config_store import ConfigStore


def main() -> int:
    p = argparse.ArgumentParser(description="Configura accounting_epoch_started_at en Dynamo config.")
    p.add_argument(
        "iso",
        nargs="?",
        help="Fecha/hora ISO en UTC (ej. 2024-06-01T00:00:00+00:00)",
    )
    p.add_argument("--clear", action="store_true", help="Borra la clave (sin corte contable).")
    args = p.parse_args()
    store = ConfigStore()
    if args.clear:
        store.set_str("accounting_epoch_started_at", "")
        print("accounting_epoch_started_at vaciado.")
        return 0
    if not args.iso:
        p.error("Indica ISO o usa --clear")
    store.set_str("accounting_epoch_started_at", args.iso.strip())
    print(f"accounting_epoch_started_at = {args.iso.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
