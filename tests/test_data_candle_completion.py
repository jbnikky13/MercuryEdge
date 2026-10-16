import pandas as pd

from mercuryedge.data import _drop_unfinished_last_bar


def _frame():
    idx = pd.date_range("2026-10-16 10:00", periods=2, freq="h", tz="UTC")
    return pd.DataFrame({
        "Open": [1.0, 1.1],
        "High": [1.1, 1.2],
        "Low": [0.9, 1.0],
        "Close": [1.05, 1.15],
        "Volume": [100, 200],
    }, index=idx)


def test_drops_current_unfinished_hourly_candle():
    frame = _frame()
    now = pd.Timestamp("2026-10-16 11:30", tz="UTC")
    result = _drop_unfinished_last_bar(frame, "1h", now)
    assert list(result.index) == [frame.index[0]]


def test_keeps_latest_candle_once_its_hour_has_closed():
    frame = _frame()
    now = pd.Timestamp("2026-10-16 12:01", tz="UTC")
    result = _drop_unfinished_last_bar(frame, "1h", now)
    assert list(result.index) == list(frame.index)


def test_empty_data_is_safe():
    assert _drop_unfinished_last_bar(pd.DataFrame(), "1h").empty
