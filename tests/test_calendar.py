from datetime import datetime, timezone

from mercuryedge.calendar import is_major_us_holiday, trading_status


def test_good_friday_2026_is_blocked():
    assert is_major_us_holiday(datetime(2026, 4, 3, tzinfo=timezone.utc).date())


def test_weekend_is_blocked():
    allowed, reason = trading_status(datetime(2026, 9, 13, 15, 0, tzinfo=timezone.utc))
    assert not allowed
    assert reason == "weekend"
