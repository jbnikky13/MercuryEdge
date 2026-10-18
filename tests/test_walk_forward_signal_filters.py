import pandas as pd

from scripts.walk_forward_signal_filters import evaluate, prepare, select_rule


def synthetic_history(days=700):
    dates = pd.date_range("2024-01-01", periods=days, freq="D", tz="UTC")
    rows = []
    for i, stamp in enumerate(dates):
        close_entry = i % 2 == 0
        rows.append({
            "scan_ts": stamp,
            "score": 60,
            "crossmarket_score": 0,
            "entry_stretch_atr": 0.5 if close_entry else 1.8,
            "holding_period": "INTRADAY_0_24H",
            "historical_win_rate_1d_pct": 50,
            "historical_win_rate_3d_pct": 50,
            "historical_win_rate_5d_pct": 50,
            "tp1_full_R_24h": ([1.15, 1.15, -1.0][i % 3] if close_entry else -1.0),
        })
    return pd.DataFrame(rows)


def test_walk_forward_filter_selection_is_training_only_and_cost_aware():
    frame = synthetic_history()
    prepared = prepare(frame)
    train = prepared[prepared.scan_ts < prepared.scan_ts.min() + pd.Timedelta(days=365)]
    selected, details = select_rule(train)
    assert selected == "STRETCH_LE_1_ATR"
    assert details["reason"] == "Selected using training window only"

    folds, costs, report = evaluate(frame)
    assert len(folds) >= 2
    assert set(costs["assumed_cost_R"]) == {0.0, 0.05, 0.1, 0.15, 0.2}
    assert report["live_filter_changed"] is False
    assert report["purge_hours"] == 24
    assert all(row["selected_rule"] in report["predeclared_rules"] for row in report["folds"])


def test_walk_forward_rejects_missing_required_columns():
    frame = synthetic_history().drop(columns=["entry_stretch_atr"])
    try:
        prepare(frame)
    except ValueError as exc:
        assert "entry_stretch_atr" in str(exc)
    else:
        raise AssertionError("missing feature should fail closed")
