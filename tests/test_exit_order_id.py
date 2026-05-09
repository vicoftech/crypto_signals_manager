from src.core.binance_client import exit_order_client_id


def test_exit_order_client_id_binance_max_length():
    tid = "550e8400-e29b-41d4-a716-446655440000"
    x = exit_order_client_id(tid)
    assert len(x) <= 36
    assert x.startswith("E")
