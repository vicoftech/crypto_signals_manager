from __future__ import annotations

import math
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


def oco_list_client_id(trade_id: str) -> str:
    compact = trade_id.replace("-", "").replace("_", "")[:34]
    return ("O" + compact)[:36]


def stop_order_client_id(trade_id: str, level: int) -> str:
    compact = trade_id.replace("-", "").replace("_", "")[:32]
    return (f"S{level}" + compact)[:36]


def exit_order_client_id(trade_id: str) -> str:
    """
    Binance newClientOrderId: max 36 chars, [a-zA-Z0-9-_].
    UUID sin guiones (32 hex) + prefijo = 33 chars.
    """
    compact = trade_id.replace("-", "").replace("_", "")[:32]
    return ("E" + compact)[:36]


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
        # symbol -> (step_size, min_qty, tick_size)
        self._lot_filters: dict[str, tuple[float, float, float]] = {}

    def _symbol_filters(self, symbol: str) -> tuple[float, float, float]:
        if symbol in self._lot_filters:
            return self._lot_filters[symbol]
        resp = requests.get(
            f"{self.base_url}/api/v3/exchangeInfo",
            params={"symbol": symbol},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        symbols = (resp.json() or {}).get("symbols") or []
        if not symbols:
            self._lot_filters[symbol] = (1e-8, 1e-8, 1e-8)
            return self._lot_filters[symbol]
        filters = symbols[0].get("filters") or []
        step = 1e-8
        min_q = 1e-8
        tick = 1e-8
        for f in filters:
            if f.get("filterType") == "LOT_SIZE":
                step = float(f.get("stepSize", step) or step)
                min_q = float(f.get("minQty", min_q) or min_q)
            elif f.get("filterType") == "PRICE_FILTER":
                tick = float(f.get("tickSize", tick) or tick)
        self._lot_filters[symbol] = (step, min_q, tick)
        return step, min_q, tick

    def _lot_step_min_qty(self, symbol: str) -> tuple[float, float]:
        step, min_q, _ = self._symbol_filters(symbol)
        return step, min_q

    def tick_size(self, symbol: str) -> float:
        _, _, tick = self._symbol_filters(symbol)
        return tick

    def round_price_to_tick(self, symbol: str, price: float, direction: str = "nearest") -> float:
        """direction: nearest | up | down"""
        tick = self.tick_size(symbol)
        if tick <= 0 or price <= 0:
            return price
        units = price / tick
        if direction == "up":
            return math.ceil(units - 1e-12) * tick
        if direction == "down":
            return math.floor(units + 1e-12) * tick
        return round(units) * tick

    def floor_quantity_to_lot(self, symbol: str, quantity: float) -> float:
        """Cantidad de venta ajustada al stepSize (redondeo hacia abajo)."""
        step, min_q = self._lot_step_min_qty(symbol)
        if quantity <= 0:
            return 0.0
        floored = math.floor(quantity / step) * step
        if floored < min_q:
            return 0.0
        return floored

    def quantity_param_string(self, symbol: str, quantity: float) -> str:
        """String `quantity` compatible con filtros LOT_SIZE del par."""
        step, _ = self._lot_step_min_qty(symbol)
        if step <= 0:
            decimals = 8
        elif step >= 1:
            decimals = 0
        else:
            step_str = f"{step:.12f}".rstrip("0").rstrip(".")
            decimals = len(step_str.split(".")[1]) if "." in step_str else 8
        decimals = min(max(decimals, 0), 12)
        return format(round(quantity, decimals), f".{decimals}f").rstrip("0").rstrip(".")

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
            "client_order_id": str(event.get("c") or ""),
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
        coid = str(new_client_order_id or "")[:36]
        params = self._sign_params(
            {
                "symbol": pair,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": f"{quote_qty_usd:.8f}",
                "newClientOrderId": coid,
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

    def place_market_sell(self, pair: str, base_quantity: float, new_client_order_id: str) -> dict[str, Any]:
        """Venta a mercado en SPOT (cantidad en activo base)."""
        qty = self.floor_quantity_to_lot(pair, base_quantity)
        if qty <= 0:
            raise ValueError(
                f"cantidad de venta invalida tras LOT_SIZE: pair={pair} base_quantity={base_quantity}"
            )
        coid = str(new_client_order_id or "")[:36]
        qty_str = self.quantity_param_string(pair, qty)
        params = self._sign_params(
            {
                "symbol": pair,
                "side": "SELL",
                "type": "MARKET",
                "quantity": qty_str,
                "newClientOrderId": coid,
            }
        )
        resp = requests.post(
            f"{self.base_url}/api/v3/order",
            headers=self._signed_headers(),
            params=params,
            timeout=max(self._timeout, 5.0),
        )
        resp.raise_for_status()
        return resp.json()

    def price_param_string(self, symbol: str, price: float) -> str:
        tick = self.tick_size(symbol)
        if tick <= 0:
            return f"{price:.8f}".rstrip("0").rstrip(".")
        if tick >= 1:
            decimals = 0
        else:
            ts = f"{tick:.12f}".rstrip("0").rstrip(".")
            decimals = len(ts.split(".")[1]) if "." in ts else 8
        decimals = min(max(decimals, 0), 12)
        return format(round(price, decimals), f".{decimals}f").rstrip("0").rstrip(".")

    def place_oco_sell_tp_sl(
        self,
        pair: str,
        base_quantity: float,
        tp_limit_price: float,
        sl_stop_trigger: float,
        sl_stop_limit_price: float,
        list_client_order_id: str,
    ) -> dict[str, Any]:
        """
        OCO SPOT venta: limite en TP (price) + STOP_LOSS_LIMIT (stopPrice/stopLimitPrice).
        """
        qty = self.floor_quantity_to_lot(pair, base_quantity)
        if qty <= 0:
            raise ValueError(f"OCO qty invalido: {pair} base_quantity={base_quantity}")
        qty_str = self.quantity_param_string(pair, qty)
        tp_px = self.round_price_to_tick(pair, tp_limit_price, "up")
        sl_trig = self.round_price_to_tick(pair, sl_stop_trigger, "down")
        sl_lim = self.round_price_to_tick(pair, sl_stop_limit_price, "down")
        lc = str(list_client_order_id or "")[:36]
        params = self._sign_params(
            {
                "symbol": pair,
                "side": "SELL",
                "quantity": qty_str,
                "price": self.price_param_string(pair, tp_px),
                "stopPrice": self.price_param_string(pair, sl_trig),
                "stopLimitPrice": self.price_param_string(pair, sl_lim),
                "stopLimitTimeInForce": "GTC",
                "listClientOrderId": lc,
            }
        )
        resp = requests.post(
            f"{self.base_url}/api/v3/order/oco",
            headers=self._signed_headers(),
            params=params,
            timeout=max(self._timeout, 10.0),
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, pair: str, order_id: int) -> dict[str, Any]:
        params = self._sign_params({"symbol": pair, "orderId": int(order_id)})
        resp = requests.delete(
            f"{self.base_url}/api/v3/order",
            headers=self._signed_headers(),
            params=params,
            timeout=max(self._timeout, 10.0),
        )
        resp.raise_for_status()
        return resp.json()

    def place_stop_loss_sell(
        self,
        pair: str,
        base_quantity: float,
        stop_trigger: float,
        stop_limit: float,
        client_order_id: str,
    ) -> dict[str, Any]:
        """STOP_LOSS_LIMIT venta: protege piso de escalera TP."""
        qty = self.floor_quantity_to_lot(pair, base_quantity)
        if qty <= 0:
            raise ValueError(f"stop sell qty invalido: {pair} qty={base_quantity}")
        trig = self.round_price_to_tick(pair, stop_trigger, "down")
        lim = self.round_price_to_tick(pair, stop_limit, "down")
        tick = self.tick_size(pair)
        if lim > trig:
            lim = max(trig - tick, trig * 0.999)
        params = self._sign_params(
            {
                "symbol": pair,
                "side": "SELL",
                "type": "STOP_LOSS_LIMIT",
                "timeInForce": "GTC",
                "quantity": self.quantity_param_string(pair, qty),
                "stopPrice": self.price_param_string(pair, trig),
                "price": self.price_param_string(pair, lim),
                "newClientOrderId": str(client_order_id or "")[:36],
            }
        )
        resp = requests.post(
            f"{self.base_url}/api/v3/order",
            headers=self._signed_headers(),
            params=params,
            timeout=max(self._timeout, 10.0),
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_order_list(self, pair: str, order_list_id: int) -> dict[str, Any]:
        params = self._sign_params({"symbol": pair, "orderListId": int(order_list_id)})
        resp = requests.delete(
            f"{self.base_url}/api/v3/orderList",
            headers=self._signed_headers(),
            params=params,
            timeout=max(self._timeout, 10.0),
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
