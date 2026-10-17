import pandas as pd

from scripts.duration_oos_diagnostics import cost_table, market_table, weekly_block_bootstrap


def test_cost_stress_penalizes_returns_monotonically():
    oos = pd.DataFrame({
        "gross_R": [1.0, -0.5, 0.5, -1.0],
        "fold": [1, 1, 2, 2],
        "scan_ts": pd.date_range("2025-01-01", periods=4, freq="D", tz="UTC"),
        "symbol": ["EURUSD"] * 4,
        "direction": ["BUY"] * 4,
        "holding_period": ["SWING_24_72H"] * 4,
    })
    result = cost_table(oos)
    assert result["mean_net_R"].is_monotonic_decreasing


def test_market_breakdown_has_group_metrics():
    oos = pd.DataFrame({
        "gross_R": [1.0, -1.0],
        "fold": [1, 2],
        "scan_ts": pd.date_range("2025-01-01", periods=2, freq="D", tz="UTC"),
        "symbol": ["EURUSD", "EURUSD"],
        "direction": ["BUY", "BUY"],
        "holding_period": ["SWING_24_72H", "SWING_24_72H"],
    })
    result = market_table(oos)
    assert len(result) == 1
    assert result.iloc[0]["trades"] == 2


def test_bootstrap_reports_small_cluster_warning():
    oos = pd.DataFrame({
        "gross_R": [1.0, -1.0],
        "fold": [1, 2],
        "scan_ts": pd.date_range("2025-01-01", periods=2, freq="D", tz="UTC"),
        "symbol": ["EURUSD"] * 2,
        "direction": ["BUY"] * 2,
        "holding_period": ["SWING_24_72H"] * 2,
    })
    result = weekly_block_bootstrap(oos)
    assert result["status"] == "too_few_week_clusters"
    assert result["confidence_interval_95_R"] is None
