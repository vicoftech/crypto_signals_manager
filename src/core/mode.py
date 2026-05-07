from __future__ import annotations

import os

MODE_SIMULATION = "simulation"
MODE_LIVE_TEST = "live_test"
MODE_TEST_LIVE = "test_live"
MODE_LIVE = "live"


def normalize_mode(mode: str | None) -> str:
    raw = str(mode or "").strip().lower()
    if raw in ("sim", MODE_SIMULATION):
        return MODE_SIMULATION
    if raw in ("real", MODE_LIVE):
        return MODE_LIVE
    if raw in (MODE_LIVE_TEST, MODE_TEST_LIVE):
        return MODE_LIVE_TEST
    return raw or MODE_SIMULATION


def is_simulation_mode(mode: str | None) -> bool:
    return normalize_mode(mode) == MODE_SIMULATION


def is_live_mode(mode: str | None) -> bool:
    normalized = normalize_mode(mode)
    return normalized in (MODE_LIVE_TEST, MODE_LIVE)


def current_live_mode() -> str:
    """
    Select live mode for new REAL orders:
    - BINANCE_ENV=testnet -> live_test
    - BINANCE_ENV=prod/mainnet/live -> live
    """
    env = str(os.getenv("BINANCE_ENV", "testnet")).strip().lower()
    if env in ("prod", "mainnet", "live"):
        return MODE_LIVE
    return MODE_LIVE_TEST
