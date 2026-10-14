import pandas as pd

from scripts.walk_forward_validation import _eligible_groups, walk_forward


def _trades():
    rows = []
    start = pd.Timestamp("2022-01-01T00:00:00Z")
    # 800 days: enough for a 365-day training window and multiple 90-day tests.
    for day in range(800):
        ts = start + pd.Timedelta(days=day)
        rows.append({
            "ts": ts.isoformat(), "symbol": "GOOD", "direction": "BUY",
            "tp1_full_R": 0.30 if day % 3 else -0.20,
        })
        rows.append({
            "ts": ts.isoformat(), "symbol": "BAD", "direction": "SELL",
            "tp1_full_R": -0.20 if day % 3 else 0.10,
        })
    return pd.DataFrame(rows)


def test_selector_uses_only_qualifying_training_groups():
    train = pd.DataFrame([
        {"symbol": "GOOD", "direction": "BUY", "tp1_full_R": 0.30}
        for _ in range(40)
    ] + [
        {"symbol": "BAD", "direction": "SELL", "tp1_full_R": -0.20}
        for _ in range(40)
    ])
    eligible = _eligible_groups(train, min_train_trades=30, selection_cost_r=0.05, min_train_edge_r=0.02)
    assert ("GOOD", "BUY") in eligible
    assert ("BAD", "SELL") not in eligible


def test_walk_forward_creates_chronological_non_overlapping_test_folds():
    folds, summary, report = walk_forward(
        _trades(), train_days=365, test_days=90, step_days=90,
        min_train_trades=30, selection_cost_r=0.05, min_train_edge_r=0.02,
        costs_r=(0.0, 0.05),
    )
    assert report["status"] == "completed"
    assert report["folds"] >= 3
    assert report["training_outcomes_are_purged_before_test_boundary"] is True
    baseline = folds[folds["mode"] == "baseline_all_signals"]
    starts = pd.to_datetime(baseline["test_start_utc"]).drop_duplicates().sort_values()
    assert (starts.diff().dropna() >= pd.Timedelta(days=90)).all()
    assert not summary.empty


def test_walk_forward_keeps_live_rules_disabled_and_compares_baseline():
    folds, _, report = walk_forward(
        _trades(), train_days=365, test_days=90, step_days=90,
        min_train_trades=30, costs_r=(0.0,),
    )
    assert report["strategy_rules_changed"] is False
    assert report["live_signal_filter_enabled"] is False
    assert set(folds["mode"]) == {"baseline_all_signals", "walk_forward_filtered"}


def test_insufficient_history_is_reported_without_fabricating_folds():
    short = _trades().iloc[:100].copy()
    folds, summary, report = walk_forward(
        short, train_days=365, test_days=90, step_days=90,
        min_train_trades=10, costs_r=(0.0,),
    )
    assert report["status"] == "insufficient_data"
    assert report["folds"] == 0
    assert folds.empty
    assert summary.empty
