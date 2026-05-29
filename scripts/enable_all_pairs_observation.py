#!/usr/bin/env python3
"""
Activa todos los pares de PairsTable y opcionalmente sim_mode=auto para observar comportamiento.

No agrega pares nuevos desde Binance; usa los ya configurados en la tabla.
Para pausar de nuevo: /pausarpar <PAR> [motivo] en Telegram.

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    PAIRS_TABLE_NAME=crypto-trading-bot-pairs \\
    PYTHONPATH=. python3 scripts/enable_all_pairs_observation.py

  # Solo ver cambios:
  ... python3 scripts/enable_all_pairs_observation.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from src.core.pairs_manager import PairsManager


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--sim-auto",
        action="store_true",
        default=True,
        help="Poner sim_mode=auto en todos (default: si)",
    )
    ap.add_argument(
        "--no-sim-auto",
        action="store_true",
        help="No cambiar sim_mode",
    )
    args = ap.parse_args()
    sim_auto = args.sim_auto and not args.no_sim_auto

    if not os.getenv("PAIRS_TABLE_NAME"):
        print("PAIRS_TABLE_NAME requerido.", file=sys.stderr)
        return 1

    reason = os.getenv(
        "ACTIVATION_REASON",
        "Observacion: bateria completa de pares activada",
    )
    pm = PairsManager()
    all_pairs = pm.get_all_pairs()
    if not all_pairs:
        print("No hay pares en la tabla.")
        return 0

    activated = 0
    sim_updated = 0
    already_active = 0

    for p in sorted(all_pairs, key=lambda x: x.pair):
        if p.active:
            already_active += 1
        else:
            if args.dry_run:
                print(f"[DRY] activar {p.pair}")
            else:
                if pm.set_pair_active(p.pair, True, reason):
                    activated += 1
                    print(f"activado {p.pair}")
                else:
                    print(f"FAIL activar {p.pair}", file=sys.stderr)

        if sim_auto:
            if p.sim_mode == "auto":
                continue
            if args.dry_run:
                print(f"[DRY] {p.pair} sim_mode=auto")
            elif pm.set_sim_mode(p.pair, "auto"):
                sim_updated += 1
                print(f"sim_auto {p.pair}")

    print(
        f"\nResumen: total={len(all_pairs)} ya_activos={already_active} "
        f"nuevos_activos={activated} sim_auto_actualizados={sim_updated}"
    )
    if not args.dry_run:
        active_n = len(pm.get_active_pairs())
        print(f"Activos ahora: {active_n}/{len(all_pairs)}")
        print("Scanner los incluira en el proximo ciclo (cada ~5 min).")
        print("Live autotrade: una op por par; tope global solo si MAX_CONCURRENT_LIVE_OPEN>0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
