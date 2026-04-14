from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


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
        text = (
            f"🎯 Oportunidad detectada\n"
            f"{opp['pair']} | {opp['strategy']}\n"
            f"Entrada: {opp['entry_actual_price']:.4f}\n"
            f"SL: {opp['sl_price']:.4f}\n"
            f"TP1: {opp['tp1_price']:.4f}\n"
            f"TP2: {opp['tp2_price']:.4f}\n"
            f"R/R: {opp['rr_ratio']:.2f}"
        )
        callback_base = f"{opp['pair']}|{opp['strategy']}|{opp['entry_actual_price']:.6f}"
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📈 ENTRAR", "callback_data": f"ENTER|{callback_base}"},
                    {"text": "🎮 SIMULAR", "callback_data": f"SIM|{callback_base}"},
                    {"text": "❌ IGNORAR", "callback_data": f"IGNORE|{callback_base}"},
                ]
            ]
        }
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
