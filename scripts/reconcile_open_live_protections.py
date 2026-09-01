#!/usr/bin/env python3
"""
Reconcilia proteccion exchange para trades live OPEN (one-shot post-deploy).

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    TRADES_TABLE_NAME=crypto-trading-bot-trades \\
    PYTHONPATH=. python3 scripts/reconcile_open_live_protections.py
"""
from __future__ import annotations

import os
import sys

from src.core.binance_client import BinanceClient
from src.core.exchange_protection import get_protection_manager, infer_protection_level
from src.core.trades_manager import TradesManager


def main() -> int:
    if not os.getenv("TRADES_TABLE_NAME"):
        print("TRADES_TABLE_NAME requerido.", file=sys.stderr)
        return 1

    trades = TradesManager()
    binance = BinanceClient()
    mgr = get_protection_manager()
    open_live = trades.get_open_live_trades()
    if not open_live:
        print("No hay trades live OPEN.")
        return 0

    ok_n = 0
    fail_n = 0
    for t in open_live:
        pair = str(t.get("pair", ""))
        tid = str(t.get("trade_id", ""))[:8]
        level = infer_protection_level(t)
        rec = mgr.reconcile_protection(binance, trades, t, force=True)
        if rec.ok:
            ok_n += 1
            print(f"OK  {pair} {level} order={rec.order_id}")
        else:
            fail_n += 1
            print(f"FAIL {pair} {level} trade={tid}… {rec.error[:120]}")

    print(f"\nResumen: ok={ok_n} fail={fail_n} total={len(open_live)}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
