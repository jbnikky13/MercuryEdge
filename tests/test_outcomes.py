import pandas as pd

from mercuryedge.outcomes import evaluate_signal
from mercuryedge.walkforward import calibrate


def candles():
    idx = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100, 100, 101, 102, 103],
            "High": [100, 101, 102, 104, 105],
            "Low": [100, 99, 100, 101, 102],
            "Close": [100, 101, 102, 103, 104],
            "Volume": [1] * 5,
        },
        index=idx,
    )


def signal():
    return {
        "direction": "BUY",
        "signal_time": "2026-01-01T00:00:00+00:00",
        "sl": 98,
        "tp1": 101,
        "tp2": 104,
    }


def test_outcome_resolves_tp2():
    result = evaluate_signal(signal(), candles(), horizon=4)
    assert result["status"] == "TP2"


def test_same_candle_sl_wins():
    frame = candles()
    frame.iloc[1, frame.columns.get_loc("High")] = 105
    frame.iloc[1, frame.columns.get_loc("Low")] = 97
    result = evaluate_signal(signal(), frame, horizon=4)
    assert result["status"] == "SL"


def test_calibration_is_bounded():
    rows = []
    for i in range(30):
        rows.append({
            "status": "TP1" if i < 24 else "SL",
            "historical_score": 6,
            "crossmarket_score": 5,
            "crossmarket_agreement": 1,
        })
    report = calibrate(rows, min_samples=20)
    modifier = report["factors"]["historical"]["POSITIVE"]["modifier"]
    assert -6 <= modifier <= 6
