import pandas as pd

from scripts.replay_live_pipeline import _latest_completed_prefix, _scan_times


def test_scan_uses_only_completed_hourly_candles():
    idx = pd.date_range("2026-10-16 04:00", periods=5, freq="h", tz="UTC")
    frame = pd.DataFrame({"Close": range(5)}, index=idx)
    # At 05:30 UTC, the 04:00 bar has closed, but the 05:00 bar is incomplete.
    prefix = _latest_completed_prefix(frame, pd.Timestamp("2026-10-16 05:30", tz="UTC"))
    assert list(prefix.index) == [idx[0]]


def test_scheduled_scan_slots_are_ordered_and_use_wat_schedule():
    idx = pd.date_range("2026-10-16 00:00", periods=72, freq="h", tz="UTC")
    frame = pd.DataFrame({"Close": range(72)}, index=idx)
    rows = _scan_times({"EURUSD": frame})
    first_day = [(ts.tz_convert("Africa/Lagos").strftime("%H:%M"), slot)
                 for ts, slot in rows
                 if ts.tz_convert("Africa/Lagos").date().isoformat() == "2026-10-16"]
    assert first_day == [
        ("01:30", "overnight"),
        ("06:30", "morning"),
        ("16:30", "afternoon"),
        ("20:30", "evening"),
    ]
