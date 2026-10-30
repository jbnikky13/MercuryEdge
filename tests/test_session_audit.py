import pandas as pd

from research.session_audit import _first_touch, session_bounds
from datetime import date


def test_session_bounds_are_africa_lagos_calendar_day():
    start, end = session_bounds(date(2026, 10, 30))
    assert (end - start).total_seconds() == 24 * 60 * 60
    assert start.hour == 23  # 00:00 WAT is 23:00 UTC on the prior date


def test_buy_stop_wins_when_stop_and_target_touch_same_bar():
    candles = pd.DataFrame(
        [{"High": 12.0, "Low": 8.0}],
        index=pd.DatetimeIndex(["2026-10-30T07:05:00Z"]),
    )
    signal = {
        "direction": "BUY", "entry": 10, "sl": 9,
        "tp1": 11, "tp2": 12,
        "signal_time": "2026-10-30T07:00:00Z",
    }
    assert _first_touch(signal, candles)["outcome"] == "AMBIGUOUS_SL_FIRST"


def test_sell_uses_high_for_stop_and_low_for_targets():
    candles = pd.DataFrame(
        [{"High": 11.1, "Low": 8.8}],
        index=pd.DatetimeIndex(["2026-10-30T07:05:00Z"]),
    )
    signal = {
        "direction": "SELL", "entry": 10, "sl": 11,
        "tp1": 9, "tp2": 8,
        "signal_time": "2026-10-30T07:00:00Z",
    }
    assert _first_touch(signal, candles)["outcome"] == "AMBIGUOUS_SL_FIRST"


def test_unresolved_signal_remains_unresolved():
    candles = pd.DataFrame(
        [{"High": 10.5, "Low": 9.5}],
        index=pd.DatetimeIndex(["2026-10-30T07:05:00Z"]),
    )
    signal = {
        "direction": "BUY", "entry": 10, "sl": 9,
        "tp1": 11, "tp2": 12,
        "signal_time": "2026-10-30T07:00:00Z",
    }
    assert _first_touch(signal, candles)["outcome"] == "UNRESOLVED"
