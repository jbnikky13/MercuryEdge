import pandas as pd

from scripts.research_historical import _settle_one, replay


def test_settlement_uses_conservative_stop_first_tie_break():
    signal = pd.Series({
        "direction": "BUY", "entry": 100.0, "risk": 1.0,
        "sl": 99.0, "tp1": 101.15, "tp2": 102.25,
    })
    future = pd.DataFrame([{"High": 102.5, "Low": 98.5, "Close": 100.0}])
    result = _settle_one(signal, future)
    assert result["outcome"] == "SL"
    assert result["tp1_hit"] is False
    assert result["tp2_full_R"] == -1.0


def test_replay_never_labels_signals_without_full_24_bar_horizon():
    idx = pd.date_range("2024-01-01", periods=260, freq="1h", tz="UTC")
    close = [1.0 + i * 0.001 for i in range(len(idx))]
    frame = pd.DataFrame({
        "Open": close,
        "High": [x + 0.0005 for x in close],
        "Low": [x - 0.0005 for x in close],
        "Close": close,
    }, index=idx)
    result = replay(frame, "TEST")
    if not result.empty:
        last_signal = pd.Timestamp(result["ts"].iloc[-1])
        assert last_signal + pd.Timedelta(hours=24) <= idx[-1]
