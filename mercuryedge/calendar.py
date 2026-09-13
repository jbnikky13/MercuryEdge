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
            date(year, 1, _nth_weekday(year, 1, 0, 3)),   # MLK Day
            date(year, 2, _nth_weekday(year, 2, 0, 3)),   # Presidents Day
            date(year, 5, _last_weekday(year, 5, 0)),     # Memorial Day
            _easter(year) - timedelta(days=2),             # Good Friday
            date(year, 9, _nth_weekday(year, 9, 0, 1)),   # Labor Day
            date(year, 11, _nth_weekday(year, 11, 3, 4)), # Thanksgiving
        }
    )
    return holidays


def early_close_days(year: int) -> set[date]:
    """Conservative early-close dates for US markets.

    MercuryEdge skips its late scan on these dates because liquidity and
    commodity/FX participation can deteriorate well before the official close.
    """
    july4 = date(year, 7, 4)
    independence_observed = july4 - timedelta(days=1) if july4.weekday() == 5 else july4
    return {
        independence_observed if independence_observed.weekday() < 5 else july4,
        date(year, 11, _nth_weekday(year, 11, 3, 4)) + timedelta(days=1),
        date(year, 12, 24),
    }


def is_major_us_holiday(day: date) -> bool:
    return day in major_us_market_holidays(day.year)


def trading_status(now_utc: datetime | None = None) -> tuple[bool, str]:
    """Return whether MercuryEdge should publish at the current moment.

    FX trades nearly 24/5, while the commodity contracts in this project have
    exchange-specific daily breaks and holiday schedules. The bot therefore
    uses a conservative US/Eastern publication window: weekdays only, no major
    US market holidays, no late Friday scans, and no late scans on early-close
    dates. This is a signal-publication guard, not a claim that every broker's
    instrument is closed at the exact same minute.
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
