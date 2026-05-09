#!/usr/bin/env python3
"""
Para operaciones ABIERTAS existentes:

- live / live_test: coloca OCO (SL + TP3) si aun no hay lista OCO activa y la posicion
  no entro aun en fase trailing (tp1_hit). Si el precio ya supero TP1, sincroniza
  Dynamo como haria el position_monitor (trailing, sin OCO).
- simulation: rellena tp3_price y trailing_tp1_tp3_step_pct si faltan (el monitor ya escanea).

El monitor de posiciones ya recorre todas las abiertas cada ~5 min; tras este script
puedes invocar la Lambda del monitor una vez para efecto inmediato.

Uso (mismo perfil/tabla que el resto del proyecto):

  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    TRADES_TABLE_NAME=crypto-trading-bot-trades \\
    CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    BINANCE_SECRET_NAME_TEST=crypto-trading-bot/binance-test \\
    BINANCE_ENV=test_live \\
    PYTHONPATH=. python3 scripts/backfill_oco_and_sync_open_trades.py

  # opcional: solo listar sin cambios
  ... python3 scripts/backfill_oco_and_sync_open_trades.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys


def _oco_list_active(trade: dict) -> bool:
    oid = trade.get("binance_oco_order_list_id")
    if oid is None:
        return False
    s = str(oid).strip()
    return bool(s) and s not in ("0", "None")


def _resolve_tp3(trade: dict, entry: float, sl: float) -> float:
    raw = float(trade.get("tp3_price") or 0)
    if raw > 0:
        return raw
    risk = entry - sl
    if risk > 0:
        return entry + risk * 4.5
    tp2 = float(trade.get("tp2_price") or entry * 1.02)
    tp1 = float(trade.get("tp1_price") or entry * 1.01)
    return tp2 + max((tp2 - tp1), entry * 0.001)


def _base_qty(trade: dict) -> float:
    q = float(trade.get("base_qty") or 0)
    if q > 0:
        return q
    ep = float(trade.get("entry_price") or 0)
    ps = float(trade.get("position_size_usd") or 0)
    if ep > 0 and ps > 0:
        return ps / ep
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No escribe Dynamo ni llama Binance")
    args = ap.parse_args()

    reg = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if reg and not os.getenv("AWS_DEFAULT_REGION"):
        os.environ["AWS_DEFAULT_REGION"] = reg

    if not os.getenv("TRADES_TABLE_NAME"):
        print("TRADES_TABLE_NAME requerido.", file=sys.stderr)
        return 1

    from src.config import settings
    from src.core.binance_client import BinanceClient
    from src.core.live_exit import attach_oco_protections
    from src.core.trades_manager import TradesManager

    tm = TradesManager()
    tm.reset_trade_list_cache()
    bn = BinanceClient()

    sims = tm.get_open_sims()
    live = tm.get_open_live_trades()

    print(f"Simulaciones abiertas: {len(sims)} | Live abiertas: {len(live)}")

    for t in sims:
        tid = str(t.get("trade_id", ""))
        updates: dict = {}
        entry = float(t.get("entry_price") or 0)
        sl = float(t.get("sl_price") or (entry * 0.99 if entry else 0))
        if entry > 0 and float(t.get("tp3_price") or 0) <= 0:
            updates["tp3_price"] = _resolve_tp3(t, entry, sl)
        if t.get("trailing_tp1_tp3_step_pct") in (None, "", 0):
            updates["trailing_tp1_tp3_step_pct"] = settings.trailing_tp1_tp3_step_pct
        if updates:
            if args.dry_run:
                print(f"[DRY] SIM {tid}: aplicaria {updates}")
            else:
                tm.update_trade(tid, updates)
                print(f"SIM {tid}: backfill {list(updates.keys())}")

    for t in live:
        tid = str(t.get("trade_id", ""))
        pair = str(t.get("pair", ""))
        if t.get("tp1_hit"):
            print(f"LIVE {tid} {pair}: ya en trailing (tp1_hit), sin OCO nuevo.")
            continue
        if _oco_list_active(t):
            print(f"LIVE {tid} {pair}: ya tiene OCO (lista {t.get('binance_oco_order_list_id')}).")
            continue

        entry = float(t.get("entry_price") or 0)
        sl = float(t.get("sl_price") or 0)
        if entry <= 0:
            print(f"LIVE {tid} {pair}: sin entry_price, omitido.")
            continue
        if sl <= 0:
            sl = entry * 0.99

        tp1 = float(t.get("tp1_price") or 0)
        tp3 = _resolve_tp3({**t, "sl_price": sl}, entry, sl)

        price = 0.0
        if not args.dry_run:
            try:
                price = float(bn.get_price(pair))
            except Exception as e:
                print(f"LIVE {tid} {pair}: precio fallo {e}, omitido.")
                continue

        if tp1 > 0 and price >= tp1:
            if args.dry_run:
                print(
                    f"[DRY] LIVE {tid} {pair}: precio {price} >= TP1 {tp1} -> "
                    "sincronizar trailing (sin OCO)"
                )
            else:
                tm.update_trade(
                    tid,
                    {
                        "tp1_hit": True,
                        "trailing_activated": True,
                        "trailing_sl_final": entry,
                        "sl_price": sl,
                        "tp3_price": tp3,
                        "trailing_tp1_tp3_step_pct": float(
                            t.get("trailing_tp1_tp3_step_pct")
                            or settings.trailing_tp1_tp3_step_pct
                        ),
                        "binance_oco_order_list_id": "",
                        "binance_oco_limit_order_id": "",
                        "binance_oco_stop_order_id": "",
                    },
                )
                print(
                    f"LIVE {tid} {pair}: sincronizado TP1→trailing (precio {price} >= {tp1}), sin OCO."
                )
            continue

        qty = _base_qty({**t, "sl_price": sl})
        if qty <= 0:
            print(f"LIVE {tid} {pair}: base_qty=0, omitido.")
            continue

        updates_pre: dict = {}
        if float(t.get("tp3_price") or 0) <= 0:
            updates_pre["tp3_price"] = tp3
        if t.get("trailing_tp1_tp3_step_pct") in (None, "", 0):
            updates_pre["trailing_tp1_tp3_step_pct"] = settings.trailing_tp1_tp3_step_pct
        if sl != float(t.get("sl_price") or 0):
            updates_pre["sl_price"] = sl

        if args.dry_run:
            print(
                f"[DRY] LIVE {tid} {pair}: OCO qty={qty:.8f} sl={sl:.8f} tp3={tp3:.8f} "
                f"+ backfill {updates_pre or '{}'}"
            )
            continue

        if updates_pre:
            tm.update_trade(tid, updates_pre)

        ok, err = attach_oco_protections(bn, tm, tid, pair, qty, sl, tp3)
        if ok:
            print(f"LIVE {tid} {pair}: OCO colocado (TP3 ~ {tp3:.8f}, SL ~ {sl:.8f}).")
        else:
            print(f"LIVE {tid} {pair}: OCO fallo: {err}")

    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
