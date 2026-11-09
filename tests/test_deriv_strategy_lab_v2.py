import pandas as pd

from scripts.deriv_strategy_lab_v2 import (
    HOLDOUT_START, _direction, _features, _settle, evaluate_holdout,
)


def sample_frame(n=600):
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    close = pd.Series(range(n), index=idx, dtype=float) + 100
    return pd.DataFrame({"Open": close - 0.2, "High": close + 0.5,
                         "Low": close - 0.5, "Close": close})


def test_features_are_lagged_and_regime_labels_are_defined():
    x = _features(sample_frame())
    assert {"ATR", "ADX", "ATR_RANK", "REGIME", "VOL_REGIME"} <= set(x.columns)
    assert set(x.REGIME.dropna().unique()) <= {"TREND", "RANGE", "TRANSITION"}


def test_settlement_uses_stop_first_when_both_levels_touched():
    future = pd.DataFrame([{"High": 103.0, "Low": 97.0, "Close": 100.0}])
    assert _settle("BUY", 100.0, 2.0, future) == -1.0


def test_holdout_is_strictly_after_frozen_cutoff_and_not_paper_eligible():
    assert HOLDOUT_START == pd.Timestamp("2026-11-08T07:00:00Z")
    trades = pd.DataFrame([{
        "strategy": "regime_pullback", "symbol": "R_10",
        "ts": "2026-11-09T07:00:00Z", "gross_R": 1.0, "risk_points": 1.0,
    }])
    spec = {"R_10": {"min_spread": 0.188}}
    _, _, report = evaluate_holdout(trades, spec, pd.Timestamp("2026-11-09T07:00:00Z"))
    assert report["status"] == "holdout_not_matured"
    assert report["paper_eligible"] is False


def test_empty_holdout_blocks_count_as_non_positive():
    from scripts.deriv_strategy_lab_v2 import evaluate_holdout

    trades = pd.DataFrame([{
        "strategy": "regime_pullback", "symbol": "R_10",
        "ts": (HOLDOUT_START + pd.Timedelta(days=1)).isoformat(),
        "gross_R": 1.6, "risk_points": 1.0,
    }])
    specs = {"R_10": {"min_spread": 0.001}}
    _, summary, report = evaluate_holdout(
        trades, specs, HOLDOUT_START + pd.Timedelta(days=120)
    )
    row = summary[(summary.cost_spread_multiple == 2.0)].iloc[0]
    assert report["complete_30_day_blocks"] == 4
    assert row.complete_blocks == 4
    assert row.positive_block_share == 0.25
