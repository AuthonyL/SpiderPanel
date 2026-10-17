"""WQ days use New York calendar midnights; log files use local dates."""

from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta
import time
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class WQWindow:
    day: date
    start: float
    end: float
    local_dates: tuple[date, ...]


def wq_day(ts=None):
    """Return the New York calendar date containing an epoch timestamp."""
    return datetime.fromtimestamp(time.time() if ts is None else ts, NEW_YORK).date()


def wq_window(day=None, *, now=None):
    """Return [midnight, next midnight), including DST and local log-file dates."""
    day = wq_day(now) if day is None else day
    start = datetime.combine(day, day_time.min, NEW_YORK).timestamp()
    end = datetime.combine(day + timedelta(days=1), day_time.min, NEW_YORK).timestamp()
    first = datetime.fromtimestamp(start).date()
    last = datetime.fromtimestamp(end-1).date()
    local_dates = tuple(first + timedelta(days=index) for index in range((last-first).days+1))
    return WQWindow(day, start, end, local_dates)
