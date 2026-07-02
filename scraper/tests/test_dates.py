"""Date parsers — the year-inference logic is the classic once-a-year bug
(events in January get stamped with December's year, or vice versa), so the
Dec->Jan rollover cases are frozen in time with freezegun."""
from freezegun import freeze_time

import scraper_core as sc


@freeze_time("2026-06-15")
def test_burren_same_month():
    assert sc.parse_burren_date("MONDAY JUNE 8", "8:30pm:") == "2026-06-08T20:30:00"


@freeze_time("2026-06-15")
def test_burren_range_uses_start():
    # "3-6pm" collapses to the 3pm start
    assert sc.parse_burren_date("FRIDAY JULY 4", "3-6pm:") == "2026-07-04T15:00:00"


@freeze_time("2026-06-15")
def test_burren_multi_time_uses_first():
    assert sc.parse_burren_date("SUNDAY JULY 5", "10:30am, 12:30pm") == "2026-07-05T10:30:00"


@freeze_time("2026-12-20")
def test_burren_january_rolls_to_next_year():
    # In late December, a January event must be next year, not this one.
    assert sc.parse_burren_date("FRIDAY JANUARY 9", "8pm:") == "2027-01-09T20:00:00"


@freeze_time("2026-12-20")
def test_burren_december_stays_this_year():
    assert sc.parse_burren_date("MONDAY DECEMBER 28", "9pm:") == "2026-12-28T21:00:00"


def test_burren_unparseable_returns_none():
    assert sc.parse_burren_date("SOMEDAY", "later") is None


@freeze_time("2026-06-30")
def test_mideast_same_year():
    assert sc.parse_mideast_datetime("6.30", "Show: 5:00PM") == "2026-06-30T17:00:00"


@freeze_time("2026-12-28")
def test_mideast_january_rolls_forward():
    # 60-day past window: a Jan 5 show viewed on Dec 28 rolls to next year.
    assert sc.parse_mideast_datetime("1.5", "Show: 8:00PM") == "2027-01-05T20:00:00"


def test_mideast_bad_input_returns_none():
    assert sc.parse_mideast_datetime("not-a-date", "whenever") is None


def test_wix_datetime():
    assert sc.parse_wix_datetime("June 6, 2026", "2:00 PM") == "2026-06-06T14:00:00"


def test_wix_missing_returns_none():
    assert sc.parse_wix_datetime("", "2:00 PM") is None
