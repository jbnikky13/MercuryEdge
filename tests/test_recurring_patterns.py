import numpy as np
import pandas as pd

from scripts.discover_recurring_patterns import discover_patterns


def test_discovers_repeating_calendar_patterns_and_pair_correlations():
    idx = pd.date_range("2015-01-01", periods=365 * 8, freq="D", tz="UTC")
    # Repeatable weekday drift with a small deterministic oscillation.
    n = np.arange(len(idx))
    a_returns = np.where(idx.dayofweek == 0, 0.002, -0.0002) + 0.001 * np.sin(n / 7)
    b_returns = a_returns * 0.8 + 0.0001 * np.cos(n / 11)
    a_close = 100 * np.cumprod(1 + a_returns)
    b_close = 80 * np.cumprod(1 + b_returns)
    frames = {
        "ALPHA": pd.DataFrame({"Close": a_close}, index=idx),
        "BETA": pd.DataFrame({"Close": b_close}, index=idx),
    }

    patterns, correlations, report = discover_patterns(frames)
    assert not patterns.empty
    assert {"weekday", "calendar_month", "calendar_month+weekday"}.issubset(set(patterns["pattern"]))
    assert not correlations.empty
    assert correlations.iloc[0]["daily_return_correlation"] > 0.5
    assert report["markets_with_daily_history"] == 2


def test_insufficient_history_does_not_create_patterns():
    idx = pd.date_range("2025-01-01", periods=50, freq="D", tz="UTC")
    frames = {"SHORT": pd.DataFrame({"Close": np.arange(50) + 100}, index=idx)}
    patterns, correlations, report = discover_patterns(frames)
    assert patterns.empty
    assert correlations.empty
    assert report["reported_pattern_rows"] == 0
