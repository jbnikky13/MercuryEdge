from __future__ import annotations

from calendar import monthcalendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int:
    weeks = monthcalendar(year, month)
    return [week[weekday] for week in weeks if week[weekday]][n - 1]


def _last_weekday(year: int, month: int, weekday: int) -> int:
    weeks = monthcalendar(year, month)
    return [week[weekday] for week in weeks if week[weekday]][-1]


def _easter(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
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
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _observed_fixed(year: int, month: int, day: int) -> set[date]:
    actual = date(year, month, day)
    if actual.weekday() == 5:  # Saturday -> Friday
        return {actual, actual - timedelta(days=1)}
    if actual.weekday() == 6:  # Sunday -> Monday
        return {actual, actual + timedelta(days=1)}
    return {actual}


def major_us_market_holidays(year: int) -> set[date]:
    holidays = set()
    for month, day in [(1, 1), (6, 19), (7, 4), (12, 25)]:
        holidays |= _observed_fixed(year, month, day)

    holidays.update(
        {
            date(year, 1, _nth_weekday(year, 1, 0, 3)),
            date(year, 2, _nth_weekday(year, 2, 0, 3)),
            date(year, 5, _last_weekday(year, 5, 0)),
            _easter(year) - timedelta(days=2),
            date(year, 9, _nth_weekday(year, 9, 0, 1)),
            date(year, 11, _nth_weekday(year, 11, 3, 4)),
        }
    )
    return holidays


def early_close_days(year: int) -> set[date]:
    """Conservative US-market early-close dates."""
    july4 = date(year, 7, 4)
    if july4.weekday() == 5:
        july_early = july4 - timedelta(days=1)
    elif july4.weekday() == 6:
        july_early = july4 + timedelta(days=1)
    else:
        july_early = july4

    thanksgiving = date(year, 11, _nth_weekday(year, 11, 3, 4))
    return {
        july_early,
        thanksgiving + timedelta(days=1),
        date(year, 12, 24),
    }


def is_major_us_holiday(day: date) -> bool:
    return day in major_us_market_holidays(day.year)


def trading_status(now_utc: datetime | None = None) -> tuple[bool, str]:
    """Return whether MercuryEdge should publish at the current moment.

    FX is generally 24/5, while commodity contracts have exchange-specific
    daily breaks and holiday schedules. This guard is deliberately conservative
    and controls signal publication rather than claiming every broker is closed
    at exactly the same minute.
    """
    now = (now_utc or datetime.now(UTC)).astimezone(ET)

    if now.weekday() >= 5:
        return False, "weekend"
    if is_major_us_holiday(now.date()):
        return False, "major US market holiday"
    if now.weekday() == 4 and now.time() >= time(15, 0):
        return False, "late Friday liquidity window"
    if now.date() in early_close_days(now.year) and now.time() >= time(13, 0):
        return False, "early-close day late session"
    if now.time() >= time(16, 0):
        return False, "past 16:00 ET scan cutoff"

    return True, "open scan window"
