from src.core.filters import needs_drift_recalc, passes_quality_filters


def test_quality_filters():
    assert passes_quality_filters({"rr_ratio": 3.0, "sl_pct": 0.01}) is True
    assert passes_quality_filters({"rr_ratio": 1.0, "sl_pct": 0.01}) is False


def test_drift():
    assert needs_drift_recalc(100.0, 100.5) is True
