#!/usr/bin/env python3
from __future__ import annotations

"""
Cierra operaciones ABIERTAS en la tabla de trades.

- Por defecto: todas (SIM y REAL).
- Con --simulation-only: solo modo simulation.

Cierra al precio de entrada (P&L ~0) con motivo MANUAL.

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 AWS_DEFAULT_REGION=ap-northeast-1 \\
    TRADES_TABLE_NAME=crypto-trading-bot-trades \\
    CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/cancel_all_open_trades.py

  Solo simulacion:
    ... python3 scripts/cancel_all_open_trades.py --simulation-only
"""

import argparse
import os

from src.core.trades_manager import TradesManager


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--simulation-only",
        action="store_true",
        help="Solo cerrar operaciones con mode=simulation",
    )
    args = ap.parse_args()

    if os.getenv("AWS_REGION") and not os.getenv("AWS_DEFAULT_REGION"):
        os.environ["AWS_DEFAULT_REGION"] = os.environ["AWS_REGION"]

    tm = TradesManager()
    abiertos = (
        tm.list_open(mode="simulation")
        if args.simulation_only
        else tm.list_open()
    )
    if not abiertos:
        print("No hay operaciones abiertas (con el filtro indicado).")
        return 0

    label = "simulation" if args.simulation_only else "todas"
    print(f"Encontradas {len(abiertos)} operaciones abiertas ({label}). Cerrando...")
    for t in abiertos:
        trade_id = str(t.get("trade_id"))
        pair = str(t.get("pair", ""))
        mode = str(t.get("mode", ""))
        entry = float(t.get("entry_price", 0) or 0)
        print(f"- Cerrando {trade_id} {pair} mode={mode} a entry={entry}")
        tm.close_trade(trade_id, "MANUAL", entry)
    print("OK, cierre MANUAL aplicado segun filtro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

