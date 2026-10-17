import pytest

from scripts.duration_variant_replay import build_variant


def test_variants_create_distinct_entry_time_exit_geometry():
    signal = {"scan_ts": "2025-01-01T00:00:00Z", "symbol": "EURUSD",
              "direction": "BUY", "entry": 1.1, "sl": 1.09, "score": 80}
    intraday = build_variant(signal, "INTRADAY_0_24H")
    swing = build_variant(signal, "SWING_24_72H")
    position = build_variant(signal, "POSITION_3_5D")

    assert intraday["sl"] == pytest.approx(1.09)
    assert swing["sl"] == pytest.approx(1.085)
    assert position["sl"] == pytest.approx(1.08)
    assert intraday["tp1"] != swing["tp1"] != position["tp1"]
    assert [intraday["variant_horizon_bars"], swing["variant_horizon_bars"],
            position["variant_horizon_bars"]] == [24, 72, 120]


def test_sell_geometry_is_mirrored_correctly():
    signal = {"symbol": "EURUSD", "direction": "SELL", "entry": 1.1, "sl": 1.11}
    variant = build_variant(signal, "SWING_24_72H")
    assert variant["sl"] == pytest.approx(1.115)
    assert variant["tp1"] < variant["entry"] < variant["sl"]


def test_invalid_risk_and_duration_fail_closed():
    with pytest.raises(ValueError):
        build_variant({"direction": "BUY", "entry": 1.1, "sl": 1.1}, "INTRADAY_0_24H")
    with pytest.raises(ValueError):
        build_variant({"direction": "BUY", "entry": 1.1, "sl": 1.09}, "UNKNOWN")
