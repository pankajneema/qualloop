"""Plant-local dates and calendar-month periods (ADR-005 section 3, A-52).

Instants are UTC; business dates are interpreted in the plant timezone. Only what P01 needs lives here; metrics and
snapshots (P07) build on `month_period`.
"""

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class MonthPeriod:
    """A calendar month in a plant timezone. An instant belongs to it iff `start_utc <= ts < cutoff`."""

    start: date
    end: date
    start_utc: datetime
    cutoff: datetime


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"unknown timezone: {tz!r}") from exc


def is_valid_timezone(tz: str) -> bool:
    try:
        zone(tz)
    except ValueError:
        return False
    return True


def plant_today(tz: str, now: datetime | None = None) -> date:
    """The business date in the plant timezone (`now` defaults to the current instant)."""
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(zone(tz)).date()


def _local_midnight_utc(tz: ZoneInfo, day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def month_period(tz: str, year: int, month: int) -> MonthPeriod:
    """First/last date of the month plus its UTC start and cutoff ((end + 1 day) 00:00 plant-local, in UTC)."""
    zone_info = zone(tz)
    last_day = calendar.monthrange(year, month)[1]
    start, end = date(year, month, 1), date(year, month, last_day)
    return MonthPeriod(
        start=start,
        end=end,
        start_utc=_local_midnight_utc(zone_info, start),
        cutoff=_local_midnight_utc(zone_info, end + timedelta(days=1)),
    )
