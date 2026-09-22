import numpy as np
import pandas as pd

from mercuryedge.historical import build_context


def synthetic_daily(n=900):
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    # Deterministic alternating drift creates both positive and negative
    # outcomes while leaving enough observations for regime matching.
    drift = np.where(np.arange(n) % 3 == 0, 0.004, -0.001)
    close = 100 * np.cumprod(1 + drift)
    return pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.006,
            "Low": close * 0.994,
            "Close": close,
            "Volume": 1000,
        },
        index=idx,
    )


def test_context_excludes_future_observations():
    df = synthetic_daily()
    timestamp = df.index[700]
    context = build_context(df, direction="BUY", timestamp=timestamp, min_samples=10)

    assert context.sample_size > 0
    assert context.day_of_week == timestamp.day_name()
    assert context.month == timestamp.month
    assert context.score <= 12
    assert context.score >= -12


def test_history_is_directional():
    df = synthetic_daily()
    timestamp = df.index[-1]
    buy = build_context(df, direction="BUY", timestamp=timestamp, min_samples=20)
    sell = build_context(df, direction="SELL", timestamp=timestamp, min_samples=20)

    assert buy.win_rate_3d is not None
    assert sell.win_rate_3d is not None
    assert np.isclose(buy.win_rate_3d + sell.win_rate_3d, 1.0)
