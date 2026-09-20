"""The only module that knows about the business timezone.

Instants are stored and compared in UTC. Rule periods and the 30-day window are
expressed in business dates (Africa/Johannesburg), so a dispense at 22:30 UTC on
14 March is governed by the rule in force on 15 March.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import get_settings

BUSINESS_TZ = ZoneInfo(get_settings().business_timezone)


def business_date(instant: datetime) -> date:
    return instant.astimezone(BUSINESS_TZ).date()


def start_of_business_day(day: date) -> datetime:
    """The UTC instant at which `day` begins in the business timezone."""
    return datetime(day.year, day.month, day.day, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


def window_start(window_end: datetime, days: int) -> datetime:
    """UTC lower bound (inclusive) of the `days`-day window ending at `window_end`.

    The window covers `days` business dates, the last of which is the business date
    of `window_end`.
    """
    first_day = business_date(window_end) - timedelta(days=days - 1)
    return start_of_business_day(first_day)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
