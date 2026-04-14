from __future__ import annotations

from datetime import datetime, timezone


def active_sessions_utc(dt: datetime) -> list[str]:
    """Sesiones de mercado crypto (UTC) con solapes habituales."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    h = dt.hour
    out: list[str] = []
    if h >= 22 or h < 8:
        out.append("ASIA")
    if 7 <= h < 16:
        out.append("EUROPA")
    if 13 <= h < 22:
        out.append("USA")
    return out


def format_market_session(dt: datetime) -> str:
    sessions = active_sessions_utc(dt)
    if not sessions:
        return "OFF"
    return " + ".join(sessions)


def format_market_session_from_iso(started_at: str) -> str:
    if not started_at:
        return "desconocido"
    try:
        s = started_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return format_market_session(dt)
    except (ValueError, TypeError):
        return "desconocido"
