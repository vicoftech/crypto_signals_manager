from __future__ import annotations

import logging

from src.core.binance_client import BinanceClient
from src.core.config_store import ConfigStore

logger = logging.getLogger(__name__)
config = ConfigStore()
binance = BinanceClient()


def handler(event, context):
    listen_key = config.get_str("binance_listen_key", "")
    if not listen_key:
        listen_key = binance.create_listen_key()
        config.set_str("binance_listen_key", listen_key)
        logger.info("created new listenKey")
        return {"ok": True, "listen_key_created": True}
    binance.keepalive_listen_key(listen_key)
    logger.info("listenKey refreshed")
    return {"ok": True, "listen_key_refreshed": True}
