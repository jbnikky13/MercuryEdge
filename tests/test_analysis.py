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
    result = analyze(add_indicators(sample_data(250)))
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



def test_overextended_entries_are_rejected():
    # The final candle is more than 3 ATR from EMA20; the replay found this
    # chase zone materially weaker than entries near the short-term mean.
    assert analyze(add_indicators(sample_data(260))) is None



def test_holding_horizon_requires_strong_mature_analogue_evidence():
    from mercuryedge.analysis import _historical_holding_period
    from mercuryedge.historical import HistoricalContext

    base = dict(
        score=0, confidence=0.4, sample_size=60, day_of_week="Monday", month=1,
        volatility_regime="NORMAL", trend_regime="BULLISH",
        avg_1d_return=0.001, avg_3d_return=0.002, avg_5d_return=0.003,
        win_rate_3d=0.56, win_rate_1d=0.56, win_rate_5d=0.57, note="test",
    )
    assert _historical_holding_period(HistoricalContext(**base)) == "INTRADAY_0_24H"

    weak_hit_rate = dict(base, win_rate_1d=0.51, win_rate_3d=0.52, win_rate_5d=0.53)
    assert _historical_holding_period(HistoricalContext(**weak_hit_rate)) == "NO_HORIZON_EDGE"

    small_sample = dict(base, sample_size=19)
    assert _historical_holding_period(HistoricalContext(**small_sample)) == "NO_HORIZON_EDGE"

    negative_mean = dict(base, avg_1d_return=-0.001, avg_3d_return=-0.002, avg_5d_return=-0.003)
    assert _historical_holding_period(HistoricalContext(**negative_mean)) == "NO_HORIZON_EDGE"
