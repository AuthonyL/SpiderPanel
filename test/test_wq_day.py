"""WQ boundaries follow New York calendar days; tracker paths remain local."""

from datetime import date, datetime
import time
from zoneinfo import ZoneInfo

import pytest

from SpiderPanel import wq_day as days


SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def shanghai_local(monkeypatch):
    try:
        with monkeypatch.context() as environment:
            environment.setenv("TZ", "Asia/Shanghai")
            time.tzset()
            yield
    finally:
        time.tzset()


@pytest.mark.parametrize("local, expected", [
    (datetime(2026, 10, 15, 11, 59, 59, tzinfo=SHANGHAI), date(2026, 10, 14)),
    (datetime(2026, 10, 15, 12, tzinfo=SHANGHAI), date(2026, 10, 15)),
    (datetime(2026, 11, 2, 12, 59, 59, tzinfo=SHANGHAI), date(2026, 11, 1)),
    (datetime(2026, 11, 2, 13, tzinfo=SHANGHAI), date(2026, 11, 2)),
])
def test_wq_day_switches_at_bjt_noon_or_one_in_winter(local, expected):
    assert days.wq_day(local.timestamp()) == expected


@pytest.mark.parametrize("day, hours, local_start, local_end", [
    (date(2026, 10, 15), 24, datetime(2026, 10, 15, 12, tzinfo=SHANGHAI),
     datetime(2026, 10, 16, 12, tzinfo=SHANGHAI)),
    (date(2026, 3, 8), 23, datetime(2026, 3, 8, 13, tzinfo=SHANGHAI),
     datetime(2026, 3, 9, 12, tzinfo=SHANGHAI)),
    (date(2026, 11, 1), 25, datetime(2026, 11, 1, 12, tzinfo=SHANGHAI),
     datetime(2026, 11, 2, 13, tzinfo=SHANGHAI)),
])
def test_calendar_midnights_include_dst_and_both_local_files(shanghai_local, day, hours, local_start, local_end):
    window = days.wq_window(day)
    assert window.day == day
    assert window.start == local_start.timestamp()
    assert window.end == local_end.timestamp()
    assert window.end-window.start == hours*3600
    assert window.local_dates == (local_start.date(), local_end.date())
    assert days.wq_day(window.start) == day
    assert days.wq_day(window.end-1) == day
    assert days.wq_day(window.end) != day


def test_default_day_uses_epoch_clock_in_new_york(monkeypatch):
    now = datetime(2026, 10, 16, 0, 1, tzinfo=SHANGHAI).timestamp()
    monkeypatch.setattr(days.time, "time", lambda: now)
    assert days.wq_day() == date(2026, 10, 15)
    assert days.wq_window().day == days.wq_window(now=now).day == date(2026, 10, 15)
