from src.lambdas.position_monitor.handler import _is_hard_sell_failure, _should_notify_exit_fail
from datetime import datetime, timedelta, timezone


def test_should_notify_first_failure():
    assert _should_notify_exit_fail(None, 60) is True
    assert _should_notify_exit_fail("", 60) is True


def test_should_not_notify_within_cooldown():
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert _should_notify_exit_fail(recent, 60) is False


def test_should_notify_after_cooldown():
    old = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
    assert _should_notify_exit_fail(old, 60) is True


def test_hard_sell_failure_detects_400():
    err = "400 Client Error: Bad Request for url: https://testnet.binance.vision/api/v3/order"
    assert _is_hard_sell_failure(err) is True
    assert _is_hard_sell_failure("Account has insufficient balance") is True
    assert _is_hard_sell_failure("temporary network glitch") is False
