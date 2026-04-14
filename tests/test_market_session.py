from datetime import datetime, timezone

from src.core.market_session import active_sessions_utc, format_market_session, format_market_session_from_iso


def test_asia_midnight_utc():
    dt = datetime(2026, 4, 14, 2, 0, tzinfo=timezone.utc)
    assert active_sessions_utc(dt) == ["ASIA"]


def test_europa_usa_overlap():
    dt = datetime(2026, 4, 14, 14, 0, tzinfo=timezone.utc)
    assert active_sessions_utc(dt) == ["EUROPA", "USA"]


def test_format_from_iso():
    assert "EUROPA" in format_market_session_from_iso("2026-04-14T14:00:00+00:00")


def test_europa_only_noon():
    assert format_market_session(datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc)) == "EUROPA"
