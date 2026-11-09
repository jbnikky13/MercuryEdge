import pandas as pd

from scripts.deriv_strategy_lab import (
    _candidate_direction,
    _non_overlapping,
    walk_forward_candidates,
)


def test_trend_pullback_requires_aligned_trend_and_confirmation():
    row = pd.Series({
        "EMA20": 105.0, "EMA50": 103.0, "EMA200": 100.0,
        "Low": 104.9, "High": 106.0, "Close": 105.5, "Open": 105.0,
        "ATR": 2.0, "RSI": 58.0, "MACD": 1.5, "MACD_SIGNAL": 1.0,
    })
    previous = row.copy()
    assert _candidate_direction("trend_pullback", row, previous) == "BUY"

    row["EMA50"] = 106.0
    assert _candidate_direction("trend_pullback", row, previous) is None


def test_overlap_suppression_is_separate_for_each_strategy():
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    trades = pd.DataFrame([
        {"strategy": "trend_pullback", "symbol": "R_25", "direction": "BUY", "ts": base, "tp1_full_R": 1.0},
        {"strategy": "trend_pullback", "symbol": "R_25", "direction": "BUY", "ts": base + pd.Timedelta(hours=1), "tp1_full_R": -1.0},
        {"strategy": "donchian_breakout", "symbol": "R_25", "direction": "BUY", "ts": base + pd.Timedelta(hours=1), "tp1_full_R": 1.0},
        {"strategy": "trend_pullback", "symbol": "R_25", "direction": "BUY", "ts": base + pd.Timedelta(hours=24), "tp1_full_R": 1.0},
    ])
    selected = _non_overlapping(trades, 24)
    assert len(selected) == 3
    assert set(selected.strategy) == {"trend_pullback", "donchian_breakout"}


def test_walk_forward_selects_only_from_training_and_reports_costs():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    for day in range(150):
        rows.append({
            "strategy": "trend_pullback", "symbol": "R_25", "direction": "BUY",
            "ts": start + pd.Timedelta(days=day), "tp1_full_R": 1.0 if day % 3 else -0.5,
        })
    folds, summary, breakdown, report = walk_forward_candidates(
        pd.DataFrame(rows), train_days=90, test_days=30, step_days=30,
        horizon_hours=24, min_train_trades=20, selection_cost_r=0.05,
        min_train_edge_r=0.02, costs_r=(0.0, 0.05),
    )
    assert report["status"] == "completed"
    assert report["selection_uses_training_data_only"] is True
    assert not folds.empty
    assert {0.0, 0.05} == set(summary.assumed_cost_R)
    assert set(breakdown.symbol) == {"R_25"}
    assert "training_selected_groups" in set(folds["mode"])
