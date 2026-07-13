from datetime import datetime, timedelta, timezone

from src.lambdas.position_monitor.handler import _should_notify_exit_fail


def test_should_notify_first_failure():
    assert _should_notify_exit_fail(None, 60) is True
    assert _should_notify_exit_fail("", 60) is True


def test_should_not_notify_within_cooldown():
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert _should_notify_exit_fail(recent, 60) is False


def test_should_notify_after_cooldown():
    old = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
    assert _should_notify_exit_fail(old, 60) is True
