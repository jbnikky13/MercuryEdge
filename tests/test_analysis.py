import numpy as np
import pandas as pd
import pytest

from mercuryedge.analysis import add_indicators, analyze, rsi


def sample_data(n=260):
    """Deterministic trending-but-not-perfectly-monotonic market data.

    A perfectly rising series has RSI=100 and should correctly be rejected by
    the signal engine as overbought; using oscillating trend data tests the
    actual setup path instead of encoding an unrealistic expectation.
    """
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    close = pd.Series(100 + 0.08 * np.arange(n) + 11 * np.sin(np.arange(n) / 4), index=idx)
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
    assert enriched[["EMA200", "RSI", "ATR", "MACD", "MACD_SIGNAL"]].notna().all().all()


def test_analysis_returns_valid_result():
    result = analyze(add_indicators(sample_data()))
    assert result is not None
    assert result["direction"] in {"BUY", "SELL"}
    assert result["score"] <= 100
    assert result["tp1"] != result["entry"]
    assert result["tp2"] != result["entry"]
    assert result["sl"] != result["entry"]


def test_rsi_handles_edge_cases():
    rising = pd.Series(np.arange(40, dtype=float))
    falling = pd.Series(np.arange(40, 0, -1, dtype=float))
    flat = pd.Series(np.full(40, 100.0))
    assert rsi(rising).iloc[-1] == pytest.approx(100.0)
    assert rsi(falling).iloc[-1] == pytest.approx(0.0)
    assert rsi(flat).iloc[-1] == pytest.approx(50.0)


def test_short_or_invalid_data_is_handled():
    short = sample_data(100)
    assert analyze(add_indicators(short)) is None
    broken = short.drop(columns=["Close"])
    with pytest.raises(ValueError):
        add_indicators(broken)
