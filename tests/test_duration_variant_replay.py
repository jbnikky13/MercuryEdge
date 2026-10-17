import pytest

import pandas as pd

from scripts.duration_variant_replay import _future_window, build_variant


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


def test_future_window_excludes_signal_candle_even_when_timestamp_is_exact_hour():
    index = pd.date_range("2025-01-01T00:00:00Z", periods=5, freq="h")
    frame = pd.DataFrame({"Close": range(5)}, index=index)
    window = _future_window(frame, pd.Timestamp("2025-01-01T02:00:00Z"), 2)
    assert list(window["Close"]) == [3, 4]


def test_future_window_starts_at_next_bar_for_mid_hour_signal():
    index = pd.date_range("2025-01-01T00:00:00Z", periods=5, freq="h")
    frame = pd.DataFrame({"Close": range(5)}, index=index)
    window = _future_window(frame, pd.Timestamp("2025-01-01T02:30:00Z"), 2)
    assert list(window["Close"]) == [3, 4]
