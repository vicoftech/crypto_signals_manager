from __future__ import annotations

import json
import os
from functools import lru_cache

import boto3


def _resolve_mode() -> str:
    raw = str(os.getenv("BINANCE_ENV", "testnet")).strip().lower()
    if raw in ("live", "prod", "mainnet"):
        return "live"
    if raw in ("test_live", "live_test", "testnet", "sandbox", "test"):
        return "test_live"
    return "test_live"


def _secret_name_for_mode() -> str:
    mode = _resolve_mode()
    if mode == "live":
        return str(
            os.getenv("BINANCE_SECRET_NAME_LIVE", "")
            or os.getenv("BINANCE_SECRET_NAME", "")
        ).strip()
    return str(
        os.getenv("BINANCE_SECRET_NAME_TEST", "")
        or os.getenv("BINANCE_SECRET_NAME", "")
    ).strip()


@lru_cache(maxsize=1)
def get_binance_secret_payload() -> dict:
    secret_name = _secret_name_for_mode()
    if not secret_name:
        return {}
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_name)
    raw = resp.get("SecretString", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
