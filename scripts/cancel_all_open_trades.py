#!/usr/bin/env python3
from __future__ import annotations

"""
Cierra todas las operaciones ABIERTAS (SIM y REAL) en la tabla de trades.

- Usa TradesManager para reutilizar la lógica de cierre.
- Cierra al precio de entrada (P&L ~0) con motivo MANUAL.

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    TRADES_TABLE_NAME=crypto-trading-bot-trades \\
    CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/cancel_all_open_trades.py
"""

import os

from src.core.trades_manager import TradesManager


def main() -> int:
    tm = TradesManager()
    abiertos = tm.list_open()
    if not abiertos:
        print("No hay operaciones abiertas.")
        return 0

    print(f"Encontradas {len(abiertos)} operaciones abiertas. Cerrando...")
    for t in abiertos:
        trade_id = str(t.get("trade_id"))
        pair = str(t.get("pair", ""))
        mode = str(t.get("mode", ""))
        entry = float(t.get("entry_price", 0) or 0)
        print(f"- Cerrando {trade_id} {pair} mode={mode} a entry={entry}")
        tm.close_trade(trade_id, "MANUAL", entry)
    print("OK, todas las operaciones abiertas fueron cerradas (motivo MANUAL).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

