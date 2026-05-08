from __future__ import annotations

import os
import time
import hmac
import hashlib
from typing import Any, TYPE_CHECKING
from urllib.parse import urlencode

import requests
from src.core.secrets import get_binance_secret_payload

_DEFAULT_HTTP_TIMEOUT = 2.5

if TYPE_CHECKING:
    import pandas as pd


class BinanceClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        secret_payload = get_binance_secret_payload()
        self.api_key = api_key or str(os.getenv("BINANCE_API_KEY", "")).strip() or str(
            secret_payload.get("api_key", "")
        ).strip()
        self.api_secret = api_secret or str(os.getenv("BINANCE_SECRET", "")).strip() or str(
            secret_payload.get("api_secret", "")
        ).strip()
        env = (
            str(os.getenv("BINANCE_ENV", "")).strip().lower()
            or str(secret_payload.get("env", "")).strip().lower()
            or "testnet"
        )
        self.base_url = (
            "https://testnet.binance.vision"
            if env in ("test", "testnet", "sandbox", "test_live", "live_test")
            else "https://api.binance.com"
        )
        self._timeout = float(os.getenv("BINANCE_HTTP_TIMEOUT", str(_DEFAULT_HTTP_TIMEOUT)) or _DEFAULT_HTTP_TIMEOUT)

    def get_klines_df(self, pair: str, interval: str, limit: int = 100) -> pd.DataFrame:
        import pandas as pd

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
            "side": event.get("S"),
            "avg_price": float(event.get("L", 0) or 0),
            "commission": float(event.get("n", 0) or 0),
        }

    def _signed_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Missing BINANCE_API_KEY")
        return {"X-MBX-APIKEY": self.api_key}

    def _sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_secret:
            raise RuntimeError("Missing BINANCE_SECRET")
        payload = {**params, "timestamp": int(time.time() * 1000)}
        query = urlencode(payload, doseq=True)
        sig = hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = sig
        return payload

    def create_listen_key(self) -> str:
        resp = requests.post(
            f"{self.base_url}/api/v3/userDataStream",
            headers=self._signed_headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return str(resp.json().get("listenKey", ""))

    def keepalive_listen_key(self, listen_key: str) -> None:
        resp = requests.put(
            f"{self.base_url}/api/v3/userDataStream",
            headers=self._signed_headers(),
            params={"listenKey": listen_key},
            timeout=self._timeout,
        )
        resp.raise_for_status()

    def place_market_buy(self, pair: str, quote_qty_usd: float, new_client_order_id: str) -> dict[str, Any]:
        params = self._sign_params(
            {
                "symbol": pair,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": f"{quote_qty_usd:.8f}",
                "newClientOrderId": new_client_order_id,
            }
        )
        resp = requests.post(
            f"{self.base_url}/api/v3/order",
            headers=self._signed_headers(),
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_spot_balance(self, asset: str = "USDT") -> dict[str, float]:
        params = self._sign_params({"recvWindow": 5000})
        resp = requests.get(
            f"{self.base_url}/api/v3/account",
            headers=self._signed_headers(),
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        balances = data.get("balances") or []
        for b in balances:
            if str(b.get("asset", "")).upper() == asset.upper():
                free = float(b.get("free", 0) or 0)
                locked = float(b.get("locked", 0) or 0)
                return {
                    "free": free,
                    "locked": locked,
                    "total": free + locked,
                }
        return {"free": 0.0, "locked": 0.0, "total": 0.0}
