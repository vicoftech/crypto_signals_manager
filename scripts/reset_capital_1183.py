#!/usr/bin/env python3
from __future__ import annotations

"""
Resetea el capital inicial y total a 1183.0 en ConfigTable.

Uso:
  AWS_PROFILE=asap_main AWS_REGION=ap-northeast-1 \\
    CONFIG_TABLE_NAME=crypto-trading-bot-config \\
    PYTHONPATH=. python3 scripts/reset_capital_1183.py
"""

from src.core.config_store import ConfigStore


def main() -> int:
    store = ConfigStore()
    target = 1183.0
    store.set_number("capital_inicial", target)
    store.set_capital(target)
    print(f"Capital inicial y total reseteados a {target:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

