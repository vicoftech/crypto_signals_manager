from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests

_DEFAULT_HTTP_TIMEOUT = 2.5


class BinanceClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com"
        self._timeout = float(os.getenv("BINANCE_HTTP_TIMEOUT", str(_DEFAULT_HTTP_TIMEOUT)) or _DEFAULT_HTTP_TIMEOUT)

    def get_klines_df(self, pair: str, interval: str, limit: int = 100) -> pd.DataFrame:
        resp = requests.get(
            f"{self.base_url}/api/v3/klines",
            params={"symbol": pair, "interval": interval, "limit": limit},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        rows = resp.json()
        cols = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "num_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ]
        df = pd.DataFrame(rows, columns=cols)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def get_price(self, pair: str) -> float:
        resp = requests.get(
            f"{self.base_url}/api/v3/ticker/price",
            params={"symbol": pair},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return float(resp.json()["price"])

    def parse_ws_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_id": event.get("i"),
            "symbol": event.get("s"),
            "status": event.get("X"),
            "exec_type": event.get("x"),
            "avg_price": float(event.get("L", 0) or 0),
            "commission": float(event.get("n", 0) or 0),
        }
