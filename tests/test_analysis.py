import numpy as np
import pandas as pd

from mercuryedge.analysis import add_indicators, analyze


def sample_data(n=260):
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    close = pd.Series(np.linspace(100, 150, n), index=idx)
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": 1000,
        },
        index=idx,
    )


def test_indicators_exist():
    enriched = add_indicators(sample_data())
    for column in ["EMA20", "EMA50", "EMA200", "RSI", "ATR", "MACD", "MACD_SIGNAL"]:
        assert column in enriched.columns


def test_analysis_returns_valid_result():
    result = analyze(add_indicators(sample_data()))
    assert result is not None
    assert result["direction"] in {"BUY", "SELL"}
    assert result["score"] <= 100
