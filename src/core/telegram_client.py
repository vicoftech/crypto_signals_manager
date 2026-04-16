from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from src.config import binance_credentials_configured
from src.core.auto_sim_utils import calcular_pnl_circunstancial, calcular_pnl_asegurado_trailing

logger = logging.getLogger(__name__)


def format_sim_progress_message(trade: dict, current_price: float) -> str:
    """Texto de progreso P&L para una posicion SIM (mismo formato que el aviso periodico anterior)."""
    entry = float(trade.get("entry_price", 0) or 0)
    size = float(trade.get("position_size_usd", 100) or 100)
    comm_in = float(trade.get("entry_commission_usd", size * 0.001) or 0)
    pnl_usd, pnl_pct = calcular_pnl_circunstancial(entry, current_price, size, comm_in)
    emoji = "📈" if pnl_usd > 0 else ("📉" if pnl_usd < 0 else "➡️")
    if abs(pnl_pct) < 0.05:
        emoji = "➡️"
    pair = trade.get("pair", "")
    trailing = bool(trade.get("trailing_activated"))
    line_trail = ""
    if trailing and trade.get("trailing_sl_final"):
        sec, spct = calcular_pnl_asegurado_trailing(
            entry, float(trade["trailing_sl_final"]), size, comm_in
        )
        line_trail = f"\n🔒 P&L asegurado:  {sec:+.2f} USD  ({spct:+.2f}%)"
    head = f"📊 [SIM] {pair} — trailing activo" if trailing else f"📊 [SIM] {pair} — en curso"
    return (
        f"{head}\n\n"
        f"💵 Precio actual:  ${current_price:,.4f}\n"
        f"{emoji} P&L ahora:      {pnl_usd:+.2f} USD  ({pnl_pct:+.2f}%){line_trail}\n"
        f"─────────────────\n"
        f"🎯 Entrada:  ${entry:,.4f}  |  SL: ${float(trade.get('sl_price', 0)):,.4f}"
    )


class TelegramClient:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def _send(self, text: str, reply_markup: dict | None = None) -> None:
        if not self.token or not self.chat_id:
            logger.warning("Telegram token/chat_id not configured")
            return
        payload = {"chat_id": self.chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json=payload,
            timeout=15,
        ).raise_for_status()

    def send_opportunity(self, opp: dict) -> None:
        real_ok = binance_credentials_configured()
        text = (
            f"🎯 Oportunidad detectada\n"
            f"{opp['pair']} | {opp['strategy']}\n"
            f"Entrada: {opp['entry_actual_price']:.4f}\n"
            f"SL: {opp['sl_price']:.4f}\n"
            f"TP1: {opp['tp1_price']:.4f}\n"
            f"TP2: {opp['tp2_price']:.4f}\n"
            f"R/R: {opp['rr_ratio']:.2f}"
        )
        if not real_ok:
            text += "\n\n⚠️ Modo REAL deshabilitado: configura BINANCE_API_KEY y BINANCE_SECRET para registrar órdenes reales y cierre automático vía Binance."
        callback_base = f"{opp['pair']}|{opp['strategy']}|{opp['entry_actual_price']:.6f}"
        row = []
        if real_ok:
            row.append({"text": "📈 ENTRAR", "callback_data": f"ENTER|{callback_base}"})
        row.extend(
            [
                {"text": "🎮 SIMULAR", "callback_data": f"SIM|{callback_base}"},
                {"text": "❌ IGNORAR", "callback_data": f"IGNORE|{callback_base}"},
            ]
        )
        keyboard = {"inline_keyboard": [row]}
        self._send(text, keyboard)
        logger.info(
            "OPPORTUNITY sent %s %s rr=%.2f",
            opp["pair"],
            opp["strategy"],
            opp["rr_ratio"],
        )

    def send_trade_update(self, text: str) -> None:
        self._send(text)
        logger.info("Trade update sent: %s", text)

    def send_opportunity_notify_only(self, opp: dict) -> None:
        text = (
            f"📣 Oportunidad (sim deshabilitada para este par)\n"
            f"{opp['pair']} | {opp['strategy']}\n"
            f"Entrada ref: {opp['entry_actual_price']:.4f}\n"
            f"SL: {opp['sl_price']:.4f}\n"
            f"TP1: {opp['tp1_price']:.4f} | TP2: {opp['tp2_price']:.4f}\n"
            f"R/R: {opp['rr_ratio']:.2f}"
        )
        self._send(text)
        logger.info("NOTIFY_ONLY sent %s", opp.get("pair"))

    def send_auto_sim_opened(self, opp: dict) -> None:
        risk = float(opp.get("risk_usd", 0) or 0)
        sl_pct = float(opp.get("sl_pct", 0) or 0) * 100
        t = datetime.now(timezone.utc).strftime("%H:%M UTC")
        text = (
            f"🤖 AUTO-SIM ABIERTA\n\n"
            f"📊 {opp['pair']}  |  M30  |  {opp['strategy']}\n"
            f"🎯 Entrada:  ${opp['entry_actual_price']:,.2f}\n"
            f"🛑 SL:       ${opp['sl_price']:,.2f}  (-{sl_pct:.2f}%)\n"
            f"🏆 TP2:      ${opp['tp2_price']:,.2f}\n"
            f"📐 R/R:      1 : {opp['rr_ratio']:.1f}\n\n"
            f"💰 Riesgo: ${risk:.2f}\n"
            f"⏰ {t}"
        )
        self._send(text)

    def send_auto_sim_closed(
        self,
        pair: str,
        strategy: str,
        entry: float,
        exit_px: float,
        net_pnl: float,
        pct: float,
        r_mult: float,
        reason: str,
        dur_min: int,
        stats_line: str | None = None,
    ) -> None:
        win = net_pnl > 0
        head = "🤖 AUTO-SIM CERRADA  ✅ GANADORA" if win else "🤖 AUTO-SIM CERRADA  ❌ PERDEDORA"
        text = (
            f"{head}\n\n"
            f"📊 {pair}  |  {strategy}\n"
            f"📈 Entrada:   ${entry:,.2f}  →  Salida: ${exit_px:,.2f}\n"
            f"💰 P&L neto:  {net_pnl:+.2f} USD  ({pct:+.2f}%)\n"
            f"📐 R multiple: {r_mult:+.2f}\n"
            f"🔒 Cierre:    {reason}\n"
            f"⏱ Duración:  {dur_min} min"
        )
        if stats_line:
            text += f"\n\n📊 {stats_line}"
        self._send(text)

    def send_sim_progress_update(self, trade: dict, current_price: float) -> None:
        self._send(format_sim_progress_message(trade, current_price))

    def send_auto_trade_eligible_notice(self, pair: str, info: dict) -> None:
        text = (
            f"🎯 PAR LISTO PARA AUTO-TRADE (revisar)\n\n"
            f"📊 {pair}\n"
            f"Trades sim: {info.get('total_trades', 0)}\n"
            f"Winrate: {info.get('winrate', 0):.0%}\n"
            f"R avg: {info.get('r_multiple_avg', 0):.2f}\n"
            f"{info.get('reason', '')}"
        )
        self._send(text)

    def send_capital_insuficiente(self, pair: str, snapshot: dict, risk_requerido: float) -> None:
        """
        Notificacion cuando una oportunidad no se puede simular por falta de capital.
        """
        text = (
            "⚠️ SIN CAPITAL DISPONIBLE\n\n"
            f"📊 {pair}\n"
            f"Capital total:      ${snapshot['capital_total']:,.2f}\n"
            f"Capital bloqueado:  ${snapshot['capital_bloqueado']:,.2f}  "
            f"({snapshot['posiciones_abiertas']} posiciones abiertas)\n"
            f"Capital disponible: ${snapshot['capital_disponible']:,.2f}\n"
            f"Riesgo requerido:   ${risk_requerido:,.2f}\n\n"
            "→ Señal registrada pero no simulada.\n"
            "  Espera que cierren posiciones abiertas."
        )
        self._send(text)
