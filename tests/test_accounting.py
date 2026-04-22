import os

os.environ.setdefault("PAIRS_TABLE_NAME", "")
os.environ.setdefault("TRADES_TABLE_NAME", "")
os.environ.setdefault("CONFIG_TABLE_NAME", "")

from src.core.accounting import (
    format_accounting_block,
    format_accounting_line_short,
    trade_in_accounting_window,
)


def test_trade_in_accounting_empty_epoch_includes_all():
    assert trade_in_accounting_window(
        {"status": "CLOSED", "ended_at": "2020-01-01T00:00:00Z"},
        "",
    )


def test_trade_in_accounting_closed_before_epoch_excluded():
    epoch = "2024-06-15T00:00:00+00:00"
    assert not trade_in_accounting_window(
        {"status": "CLOSED", "ended_at": "2024-06-01T00:00:00Z"},
        epoch,
    )
    assert trade_in_accounting_window(
        {"status": "CLOSED", "ended_at": "2024-07-01T00:00:00Z"},
        epoch,
    )


def test_format_line_short_mentions_key_when_no_epoch():
    t = format_accounting_line_short()
    assert "accounting_epoch_started_at" in t
