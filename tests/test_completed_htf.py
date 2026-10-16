import numpy as np
import pandas as pd

from mercuryedge.upgrades import htf_trend


def test_htf_trend_ignores_unfinished_four_hour_bucket():
    idx = pd.date_range("2026-01-01", periods=900, freq="h", tz="UTC")
    close = pd.Series(100 + np.arange(len(idx)) * 0.03, index=idx)
    frame = pd.DataFrame({
        "open": close,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
    }, index=idx)

    baseline = htf_trend(frame)
    changed_partial = frame.copy()
    # Last hourly candle belongs to a 4h bucket that has not closed yet.
    changed_partial.iloc[-1, changed_partial.columns.get_loc("close")] = 1.0
    assert htf_trend(changed_partial) == baseline
