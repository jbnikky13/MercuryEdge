import numpy as np
import pandas as pd

from mercuryedge.crossmarket import build_context


def make_series(n=180, drift=0.001):
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    values = 100 * np.cumprod(np.full(n, 1 + drift))
    return pd.DataFrame(
        {"Open": values, "High": values * 1.01, "Low": values * 0.99,
         "Close": values, "Volume": 1000},
        index=idx,
    )


def test_cross_market_context_is_bounded():
    frames = {
        "XAUUSD": make_series(drift=0.001),
        "DXY": make_series(drift=-0.0005),
        "VIX": make_series(drift=-0.0002),
    }
    context = build_context("XAUUSD", "BUY", frames, window=60)
    assert -8 <= context.score <= 8
    assert 0 <= context.confidence <= 1


def test_unknown_instrument_is_neutral():
    context = build_context("UNKNOWN", "BUY", {})
    assert context.score == 0
    assert context.observations == 0
