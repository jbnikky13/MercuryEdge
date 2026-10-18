import pandas as pd

from scripts.duration_candidate_audit import audit


def test_audit_does_not_use_future_realized_holding_window_as_selection_input():
    trades = pd.DataFrame({
        "scan_ts": pd.date_range("2025-01-01", periods=2, freq="D", tz="UTC"),
        "symbol": ["EURUSD", "EURUSD"],
        "direction": ["BUY", "SELL"],
        "holding_period": ["INTRADAY_0_24H", "INTRADAY_0_24H"],
        "entry": [1.1, 1.2], "sl": [1.09, 1.21],
        "tp1": [1.11, 1.19], "tp2": [1.12, 1.18],
        "actual_holding_window": ["0_24H", "24_72H"],
        "tp1_full_R_5d": [1.0, -1.0],
    })
    result = audit(trades)
    assert result["status"] == "single_duration_label_only"
    assert result["future_actual_holding_window_used_as_selection_input"] is False
    assert result["historical_horizon_selection_is_ex_ante"] is True
    assert "actual_holding_window" in result["future_outcome_fields_present_for_grading_only"]


def test_audit_flags_multiple_labels_with_shared_exit_geometry():
    trades = pd.DataFrame({
        "scan_ts": pd.date_range("2025-01-01", periods=2, freq="D", tz="UTC"),
        "symbol": ["EURUSD", "EURUSD"],
        "direction": ["BUY", "BUY"],
        "holding_period": ["INTRADAY_0_24H", "SWING_24_72H"],
        "entry": [1.1, 1.1], "sl": [1.09, 1.09],
        "tp1": [1.11, 1.11], "tp2": [1.12, 1.12],
    })
    result = audit(trades)
    assert result["status"] == "multiple_labels_shared_exit_geometry"
    assert result["exit_geometry_varies_by_duration"] is False


def test_audit_requires_core_replay_columns():
    result = audit(pd.DataFrame({"symbol": ["EURUSD"]}))
    assert result["status"] == "invalid_input"
    assert "holding_period" in result["missing_columns"]
