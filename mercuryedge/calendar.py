from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Conservative no-signal dates for the major US market holidays that materially
# reduce liquidity in FX/US commodity markets. CME publishes instrument-specific
# holiday hours; MercuryEdge skips these dates rather than guessing at reduced
# liquidity or early-close conditions.
FIXED_HOLIDAYS = {(1, 1), (6, 19), (7, 4), (12, 25)}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int:
    from calendar import monthcalendar

    weeks = monthcalendar(year, month)
    days = [week[weekday] for week in weeks if week[weekday]]
    return days[n - 1]


def _last_weekday(year: int, month: int, weekday: int) -> int:
    from calendar import monthcalendar

    weeks = monthcalendar(year, month)
    return [week[weekday] for week in weeks if week[weekday]][-1]


def is_major_us_holiday(day) -> bool:
    # Monday holidays.
    if day.month == 1 and day.day == _nth_weekday(day.year, 1, 0, 3):  # MLK
        return True
    if day.month == 2 and day.day == _nth_weekday(day.year, 2, 0, 3):  # Presidents
        return True
    if day.month == 5 and day.day == _last_weekday(day.year, 5, 0):  # Memorial
        return True
    if day.month == 9 and day.day == _nth_weekday(day.year, 9, 0, 1):  # Labor
        return True
    if day.month == 10 and day.day == _nth_weekday(day.year, 10, 0, 2):  # Columbus
        return True
    if day.month == 11 and day.day == _nth_weekday(day.year, 11, 3, 4):  # Thanksgiving
        return True

    # Good Friday: two days before Easter Sunday.
    from datetime import date, timedelta
    a = day.year % 19
    b = day.year // 100
    c = day.year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    easter_day = (h + l - 7 * m + 114) % 31 + 1
    good_friday = date(day.year, month, easter_day) - timedelta(days=2)
    if day == good_friday:
        return True

    return (day.month, day.day) in FIXED_HOLIDAYS


def trading_status(now_utc: datetime | None = None) -> tuple[bool, str]:
    """Return whether MercuryEdge should publish at the current moment.

    The scan is deliberately conservative: weekends, major US holidays and
    late Friday sessions are skipped. Normal weekday scans are allowed before
    the 16:00 ET US cash/major liquidity cutoff.
    """
    now = (now_utc or datetime.now(ZoneInfo("UTC"))).astimezone(ET)

    if now.weekday() >= 5:
        return False, "weekend"
    if is_major_us_holiday(now.date()):
        return False, "major US holiday"
    if now.weekday() == 4 and now.time() >= time(15, 0):
        return False, "late Friday liquidity window"
    if now.time() >= time(16, 0):
        return False, "past 16:00 ET scan cutoff"

    return True, "open scan window"
