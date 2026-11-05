"""Time handling. All datetimes stored are naive UTC. Local wall-clock time is
always converted from (local date, local time, zone), never by adding 7 days in UTC."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def local_to_utc(d: date, t: time, tz: str) -> datetime:
    """Convert a local wall-clock date+time to naive UTC.

    Fold: an ambiguous time (clocks go back) uses the first occurrence (fold=0).
    Gap: a nonexistent time (clocks go forward) moves forward by the length of the
    gap, so 01:30 on spring-forward day becomes 02:30 local."""
    zone = ZoneInfo(tz)
    naive = datetime.combine(d, t)
    aware = naive.replace(tzinfo=zone, fold=0)
    return aware.astimezone(UTC).replace(tzinfo=None)


def utc_to_local(dt: datetime, tz: str) -> datetime:
    return dt.replace(tzinfo=UTC).astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def today_local(tz: str) -> date:
    return utc_to_local(now_utc(), tz).date()


def next_weekday_on_or_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def occurrence_dates(first_date: date, weekday: int, start: date, end: date):
    """Weekly local dates from max(first_date, start) to end inclusive, all on `weekday`."""
    cur = next_weekday_on_or_after(max(first_date, start), weekday)
    while cur <= end:
        yield cur
        cur += timedelta(days=7)
