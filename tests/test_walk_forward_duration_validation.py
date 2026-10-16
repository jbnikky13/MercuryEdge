import pandas as pd
import pytest

from scripts.walk_forward_duration_validation import prepare, validate


def sample_trades():
    dates = pd.date_range("2024-01-01", periods=700, freq="D", tz="UTC")
    return pd.DataFrame({
        "scan_ts": dates,
        "symbol": ["EURUSD"] * 700,
        "direction": ["BUY"] * 700,
        "holding_period": ["SWING_24_72H"] * 700,
        "tp1_full_R_5d": [0.5 if i % 3 else -1.0 for i in range(700)],
    })


def test_prepare_discards_unmatured_outcomes_and_limits_overlap():
    data = sample_trades()
    data.loc[699, "tp1_full_R_5d"] = None
    prepared = prepare(data, horizon_hours=120)
    assert prepared["tp1_full_R_5d"].notna().all()
    assert (prepared["scan_ts"].diff().dropna() >= pd.Timedelta(hours=120)).all()


def test_duration_walk_forward_is_chronological_and_reports_costs():
    folds, summary, report = validate(
        sample_trades(), train_days=180, test_days=60, step_days=60,
        horizon_hours=120, min_train_trades=8, selection_cost_r=0.05,
        min_train_edge_r=-0.2, costs_r=(0.0, 0.05),
    )
    assert report["status"] == "completed"
    assert report["training_outcomes_purged_before_test"] is True
    assert report["training_boundary_purge_hours"] == 120
    assert not folds.empty
    assert set(summary["assumed_round_trip_cost_R"]) == {0.0, 0.05}


def test_prepare_rejects_missing_duration_columns():
    with pytest.raises(ValueError, match="Missing duration-aware"):
        prepare(pd.DataFrame({"symbol": ["EURUSD"]}))
