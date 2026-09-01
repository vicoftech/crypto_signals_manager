from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from src.core.binance_client import BinanceClient
from src.core.live_exit import _cancel_exchange_protections, _oco_active
from src.core.trades_manager import TradesManager

logger = logging.getLogger(__name__)

SYNC_SYNCED = "synced"
SYNC_PENDING = "pending"
SYNC_FAILED = "failed"
SYNC_UNPROTECTED = "unprotected"

_LEVEL_TAGS = {
    "SL": "0",
    "BE": "B",
    "TP1": "1",
    "TP2": "2",
    "TP3": "3",
    "TP4": "4",
    "TP5": "5",
    "TP6": "6",
}


def protection_client_order_id(trade_id: str, protection_level: str) -> str:
    compact = trade_id.replace("-", "").replace("_", "")[:30]
    tag = _LEVEL_TAGS.get(protection_level, "0")
    return (f"S{tag}" + compact)[:36]


def infer_protection_level(trade: dict) -> str:
    level = int(trade.get("ladder_level") or 0)
    if level >= 1:
        return f"TP{level}"
    if bool(trade.get("breakeven_armed")):
        return "BE"
    return "SL"


def exchange_protection_strict() -> bool:
    return os.getenv("EXCHANGE_PROTECTION_STRICT", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def protection_max_retries() -> int:
    return max(1, int(os.getenv("PROTECTION_MAX_RETRIES", "6")))


def protection_alert_cooldown_min() -> float:
    return float(os.getenv("PROTECTION_ALERT_COOLDOWN_MIN", "30"))


def protection_broken_alert_min() -> float:
    return float(os.getenv("PROTECTION_BROKEN_ALERT_MIN", "15"))


@dataclass
class ReconcileResult:
    ok: bool
    error: str = ""
    order_id: str = ""
    recovered: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trade_qty(trade: dict, pair: str, binance: BinanceClient) -> float:
    qty = float(trade.get("base_qty") or 0)
    if qty > 0:
        return binance.floor_quantity_to_lot(pair, qty)
    entry = float(trade.get("entry_price") or 0)
    size = float(trade.get("position_size_usd") or 0)
    if entry > 0 and size > 0:
        return binance.floor_quantity_to_lot(pair, size / entry)
    return 0.0


def _is_stop_sell(order: dict) -> bool:
    side = str(order.get("side", "")).upper()
    typ = str(order.get("type", "")).upper()
    return side == "SELL" and "STOP" in typ


def _order_active(order: dict) -> bool:
    st = str(order.get("status", "")).upper()
    return st in ("NEW", "PARTIALLY_FILLED", "PENDING_NEW", "ACCEPTED")


def _price_close(a: float, b: float, tick: float) -> bool:
    if tick <= 0:
        return abs(a - b) <= 1e-9
    return abs(a - b) <= tick * 1.5


def _qty_close(a: float, b: float, step: float) -> bool:
    if step <= 0:
        return abs(a - b) <= 1e-9
    return abs(a - b) <= step * 1.5


def _trade_client_prefix(trade_id: str) -> str:
    return trade_id.replace("-", "").replace("_", "")[:30]


def _orders_for_trade(open_orders: list[dict], trade_id: str) -> list[dict]:
    prefix = _trade_client_prefix(trade_id)
    out: list[dict] = []
    for o in open_orders:
        cid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
        if cid.startswith("S") and prefix in cid:
            out.append(o)
    return out


class ExchangeProtectionManager:
    """Cancel → place → verify: paridad Dynamo ↔ Binance para stops de escalera."""

    def is_synced(self, trade: dict) -> bool:
        return str(trade.get("protection_sync_status") or "") == SYNC_SYNCED

    def has_verified_protection(self, trade: dict) -> bool:
        if not self.is_synced(trade):
            return False
        oid = str(
            trade.get("protection_order_id")
            or trade.get("binance_stop_order_id")
            or trade.get("binance_oco_stop_order_id")
            or ""
        ).strip()
        if oid and oid not in ("0", "None"):
            return True
        return _oco_active(trade) and bool(trade.get("binance_oco_order_list_id"))

    def verify_open_protection(
        self,
        binance: BinanceClient,
        trade: dict,
        *,
        expected_stop: float | None = None,
        expected_level: str | None = None,
    ) -> tuple[bool, str]:
        pair = str(trade.get("pair", ""))
        tid = str(trade.get("trade_id", ""))
        level = expected_level or infer_protection_level(trade)
        stop_px = float(
            expected_stop
            if expected_stop is not None
            else trade.get("protection_target_price")
            or trade.get("active_stop_price")
            or trade.get("sl_price")
            or 0
        )
        qty = _trade_qty(trade, pair, binance)
        if qty <= 0:
            return False, "invalid qty"

        open_orders = binance.get_open_orders(pair)
        tick = binance.tick_size(pair)
        step, _ = binance._lot_step_min_qty(pair)

        # OCO inicial (solo SL, sin escalera): verificar pierna STOP del OCO.
        if level == "SL" and _oco_active(trade) and int(trade.get("ladder_level") or 0) <= 0:
            oco_id = str(trade.get("binance_oco_order_list_id") or "")
            oco_stops = [
                o
                for o in open_orders
                if str(o.get("orderListId", "")) == oco_id and _is_stop_sell(o) and _order_active(o)
            ]
            if len(oco_stops) != 1:
                return False, f"OCO stop leg count={len(oco_stops)} list={oco_id}"
            stop_o = oco_stops[0]
            trig = float(stop_o.get("stopPrice") or 0)
            oqty = float(stop_o.get("origQty") or 0)
            if not _price_close(trig, stop_px, tick):
                return False, f"OCO stopPrice {trig} != {stop_px}"
            if not _qty_close(oqty, qty, step):
                return False, f"OCO qty {oqty} != {qty}"
            return True, ""

        client_id = protection_client_order_id(tid, level)
        expected_oid = str(
            trade.get("protection_order_id") or trade.get("binance_stop_order_id") or ""
        ).strip()

        stops = [o for o in open_orders if _is_stop_sell(o) and _order_active(o)]
        mine = _orders_for_trade(stops, tid)
        if len(mine) != 1:
            return False, f"stop orders for trade={len(mine)} (expected 1)"

        stop_o = mine[0]
        cid = str(stop_o.get("clientOrderId") or stop_o.get("origClientOrderId") or "")
        oid = str(stop_o.get("orderId") or "")
        if cid != client_id and (not expected_oid or oid != expected_oid):
            return False, f"clientOrderId mismatch {cid} != {client_id}"

        trig = float(stop_o.get("stopPrice") or 0)
        oqty = float(stop_o.get("origQty") or 0)
        if not _price_close(trig, stop_px, tick):
            return False, f"stopPrice {trig} != target {stop_px}"
        if not _qty_close(oqty, qty, step):
            return False, f"origQty {oqty} != {qty}"
        return True, ""

    def check_parity(self, binance: BinanceClient, trade: dict) -> tuple[bool, str]:
        if not self.is_synced(trade):
            return False, "protection_sync_status != synced"
        return self.verify_open_protection(binance, trade)

    def _persist(
        self,
        trades: TradesManager,
        tid: str,
        fields: dict,
    ) -> None:
        trades.update_trade(tid, fields)

    def reconcile_protection(
        self,
        binance: BinanceClient,
        trades: TradesManager,
        trade: dict,
        *,
        force: bool = False,
    ) -> ReconcileResult:
        tid = str(trade.get("trade_id", ""))
        pair = str(trade.get("pair", ""))
        level = infer_protection_level(trade)
        stop_px = float(trade.get("active_stop_price") or trade.get("sl_price") or 0)
        ladder_level = int(trade.get("ladder_level") or 0)

        if stop_px <= 0:
            return ReconcileResult(False, "invalid stop price")

        if not force and self.is_synced(trade):
            ok, err = self.check_parity(binance, trade)
            if ok:
                return ReconcileResult(True, order_id=str(trade.get("protection_order_id") or ""))

        retry = int(trade.get("protection_retry_count") or 0) + 1
        self._persist(
            trades,
            tid,
            {
                "protection_sync_status": SYNC_PENDING,
                "protection_level": level,
                "protection_target_price": stop_px,
                "protection_last_sync_at": _now_iso(),
                "protection_retry_count": retry,
            },
        )

        qty = _trade_qty(trade, pair, binance)
        if qty <= 0:
            err = f"invalid qty pair={pair}"
            self._persist(
                trades,
                tid,
                {
                    "protection_sync_status": SYNC_FAILED,
                    "protection_last_error": err[:500],
                },
            )
            return ReconcileResult(False, err)

        try:
            _cancel_exchange_protections(binance, trade, pair)
            tick = binance.tick_size(pair)
            sl_lim = binance.round_price_to_tick(
                pair, max(stop_px - tick * 2, stop_px * 0.9999), "down"
            )
            client_id = protection_client_order_id(tid, level)
            order = binance.place_stop_loss_sell(pair, qty, stop_px, sl_lim, client_id)
            order_id = str(order.get("orderId", ""))

            trade_after = dict(trade)
            trade_after.update(
                {
                    "protection_order_id": order_id,
                    "protection_client_order_id": client_id,
                    "binance_stop_order_id": order_id,
                    "binance_oco_order_list_id": "",
                    "binance_oco_limit_order_id": "",
                    "binance_oco_stop_order_id": "",
                    "active_stop_price": stop_px,
                    "ladder_level": ladder_level,
                }
            )

            ok, verr = self.verify_open_protection(
                binance,
                trade_after,
                expected_stop=stop_px,
                expected_level=level,
            )
            if not ok:
                err = f"verify failed: {verr}"
                status = SYNC_FAILED if retry >= protection_max_retries() else SYNC_PENDING
                self._persist(
                    trades,
                    tid,
                    {
                        "protection_sync_status": status,
                        "protection_last_error": err[:500],
                        "protection_order_id": order_id,
                        "protection_client_order_id": client_id,
                        "binance_stop_order_id": order_id,
                    },
                )
                return ReconcileResult(False, err, order_id=order_id)

            self._persist(
                trades,
                tid,
                {
                    "protection_sync_status": SYNC_SYNCED,
                    "protection_level": level,
                    "protection_target_price": stop_px,
                    "protection_order_id": order_id,
                    "protection_client_order_id": client_id,
                    "binance_stop_order_id": order_id,
                    "binance_oco_order_list_id": "",
                    "binance_oco_limit_order_id": "",
                    "binance_oco_stop_order_id": "",
                    "protection_last_error": "",
                    "protection_retry_count": 0,
                    "active_stop_price": stop_px,
                    "ladder_level": ladder_level,
                },
            )
            logger.info(
                "protection synced trade_id=%s pair=%s level=%s stop=%.6f order=%s",
                tid,
                pair,
                level,
                stop_px,
                order_id,
            )
            return ReconcileResult(True, order_id=order_id, recovered=retry > 1)
        except Exception as e:
            err = str(e)
            status = SYNC_FAILED if retry >= protection_max_retries() else SYNC_PENDING
            self._persist(
                trades,
                tid,
                {
                    "protection_sync_status": status,
                    "protection_last_error": err[:500],
                },
            )
            logger.warning("reconcile_protection failed trade_id=%s: %s", tid, err, exc_info=True)
            return ReconcileResult(False, err)

    def verify_oco_after_attach(
        self,
        binance: BinanceClient,
        trades: TradesManager,
        trade: dict,
    ) -> ReconcileResult:
        """Tras attach_oco_protections: marcar paridad SL si pierna STOP verificada."""
        tid = str(trade.get("trade_id", ""))
        pair = str(trade.get("pair", ""))
        stop_px = float(trade.get("sl_price") or trade.get("active_stop_price") or 0)
        level = "SL"
        ok, err = self.verify_open_protection(
            binance,
            trade,
            expected_stop=stop_px,
            expected_level=level,
        )
        if not ok:
            self._persist(
                trades,
                tid,
                {
                    "protection_sync_status": SYNC_FAILED,
                    "protection_level": level,
                    "protection_target_price": stop_px,
                    "protection_last_error": err[:500],
                    "protection_last_sync_at": _now_iso(),
                },
            )
            return ReconcileResult(False, err)

        stop_oid = str(trade.get("binance_oco_stop_order_id") or "")
        self._persist(
            trades,
            tid,
            {
                "protection_sync_status": SYNC_SYNCED,
                "protection_level": level,
                "protection_target_price": stop_px,
                "protection_order_id": stop_oid,
                "protection_client_order_id": "",
                "protection_last_error": "",
                "protection_retry_count": 0,
                "protection_last_sync_at": _now_iso(),
            },
        )
        return ReconcileResult(True, order_id=stop_oid)

    def maybe_alert_critical(
        self,
        telegram,
        trade: dict,
        error: str,
        *,
        minutes_since_iso,
    ) -> None:
        retry = int(trade.get("protection_retry_count") or 0)
        if retry < protection_max_retries():
            return
        last = str(trade.get("protection_alert_sent_at") or "")
        if last and minutes_since_iso(last) < protection_alert_cooldown_min():
            return
        pair = str(trade.get("pair", ""))
        tid = str(trade.get("trade_id", ""))[:8]
        level = infer_protection_level(trade)
        stop_px = float(trade.get("protection_target_price") or trade.get("active_stop_price") or 0)
        telegram.send_protection_critical(
            pair,
            tid,
            level,
            stop_px,
            retry,
            error,
        )
        return None

    def maybe_alert_broken_parity(
        self,
        telegram,
        trade: dict,
        error: str,
        *,
        minutes_since_iso,
    ) -> None:
        sync_at = str(trade.get("protection_last_sync_at") or trade.get("started_at") or "")
        age = minutes_since_iso(sync_at)
        if age < protection_broken_alert_min():
            return
        status = str(trade.get("protection_sync_status") or "")
        if status not in (SYNC_PENDING, SYNC_FAILED):
            return
        self.maybe_alert_critical(telegram, trade, error, minutes_since_iso=minutes_since_iso)

    def maybe_alert_stale_protected_exit(
        self,
        telegram,
        trade: dict,
        close_reason: str,
        signal_age_min: float,
    ) -> None:
        pair = str(trade.get("pair", ""))
        tid = str(trade.get("trade_id", ""))[:8]
        telegram.send_trade_update(
            f"⏳ Esperando fill en exchange ({pair})\n"
            f"trade {tid}… | motivo libro: {close_reason}\n"
            f"STOP verificado activo — sin MARKET (strict). "
            f"Senal hace {signal_age_min:.0f} min."
        )


_manager = ExchangeProtectionManager()


def get_protection_manager() -> ExchangeProtectionManager:
    return _manager
