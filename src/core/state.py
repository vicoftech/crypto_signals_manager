from __future__ import annotations

from datetime import datetime, timedelta, timezone


class CooldownState:
    def __init__(self) -> None:
        self._last_signal: dict[str, datetime] = {}

    def in_cooldown(self, pair: str, strategy: str, minutes: int) -> bool:
        key = f"{pair}#{strategy}"
        ts = self._last_signal.get(key)
        if not ts:
            return False
        return datetime.now(timezone.utc) - ts < timedelta(minutes=minutes)

    def mark(self, pair: str, strategy: str) -> None:
        self._last_signal[f"{pair}#{strategy}"] = datetime.now(timezone.utc)
