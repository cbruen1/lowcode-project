from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.timeutil import local_to_utc, occurrence_dates, utc_to_local

DUBLIN = "Europe/Dublin"
UTC_BEFORE = {  # 19:00 local expressed in UTC: winter = +0, summer (IST) = +1
}


def sundays(start, end):
    return list(occurrence_dates(start, 6, start, end))


@pytest.mark.parametrize("transition_weekend", [
    (date(2026, 3, 22), date(2026, 4, 5)),    # clocks forward 29 Mar 2026
    (date(2026, 10, 18), date(2026, 11, 1)),  # clocks back 25 Oct 2026
    (date(2027, 3, 21), date(2027, 4, 4)),    # 28 Mar 2027
    (date(2027, 10, 24), date(2027, 11, 7)),  # 31 Oct 2027
    (date(2028, 3, 19), date(2028, 4, 2)),    # 26 Mar 2028
    (date(2028, 10, 22), date(2028, 11, 5)),  # 29 Oct 2028
])
def test_1900_stays_1900_local_across_every_transition(transition_weekend):
    start, end = transition_weekend
    for d in occurrence_dates(start - __import__("datetime").timedelta(days=start.weekday()), 0, start, end):
        utc = local_to_utc(d, time(19, 0), DUBLIN)
        assert utc_to_local(utc, DUBLIN) == datetime.combine(d, time(19, 0))


def test_utc_offset_changes_but_local_time_does_not_spring_2026():
    before = local_to_utc(date(2026, 3, 23), time(19, 0), DUBLIN)
    after = local_to_utc(date(2026, 3, 30), time(19, 0), DUBLIN)
    assert before.hour == 19 and after.hour == 18  # UTC shifts an hour earlier after clocks go forward


def test_utc_offset_changes_autumn_2026():
    before = local_to_utc(date(2026, 10, 19), time(19, 0), DUBLIN)
    after = local_to_utc(date(2026, 10, 26), time(19, 0), DUBLIN)
    assert before.hour == 18 and after.hour == 19


@pytest.mark.parametrize("day,expected_utc", [
    (date(2026, 3, 29), datetime(2026, 3, 29, 1, 30)),
    (date(2027, 3, 28), datetime(2027, 3, 28, 1, 30)),
    (date(2028, 3, 26), datetime(2028, 3, 26, 1, 30)),
])
def test_gap_01_30_moves_forward_to_02_30(day, expected_utc):
    utc = local_to_utc(day, time(1, 30), DUBLIN)
    assert utc == expected_utc
    assert utc_to_local(utc, DUBLIN).time() == time(2, 30)


@pytest.mark.parametrize("day", [date(2026, 10, 25), date(2027, 10, 31), date(2028, 10, 29)])
def test_fold_uses_first_occurrence(day):
    utc = local_to_utc(day, time(1, 30), DUBLIN)
    assert utc == datetime(day.year, day.month, day.day, 0, 30)  # first (summer time) 01:30


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25), date(2027, 3, 28),
                                 date(2027, 10, 31), date(2028, 3, 26), date(2028, 10, 29)])
def test_sunday_class_on_transition_day(day):
    assert day.weekday() == 6
    utc = local_to_utc(day, time(19, 0), DUBLIN)
    assert utc_to_local(utc, DUBLIN) == datetime.combine(day, time(19, 0))
    seq = sundays(day - __import__("datetime").timedelta(days=14), day + __import__("datetime").timedelta(days=14))
    assert len(seq) == 5
    for d in seq:
        assert utc_to_local(local_to_utc(d, time(19, 0), DUBLIN), DUBLIN).time() == time(19, 0)


def test_all_generated_dates_keep_weekday():
    ds = list(occurrence_dates(date(2026, 1, 5), 0, date(2026, 1, 5), date(2028, 12, 31)))
    assert all(d.weekday() == 0 for d in ds)
    assert all((b - a).days == 7 for a, b in zip(ds, ds[1:]))


def test_other_zone_works():
    utc = local_to_utc(date(2026, 7, 1), time(9, 0), "America/New_York")
    assert utc == datetime(2026, 7, 1, 13, 0)
