from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CollectionWindow:
    timezone_name: str
    run_at_local: datetime
    start_local: datetime
    end_local: datetime
    start_utc: datetime
    end_utc: datetime

    def contains_utc(self, value: datetime) -> bool:
        if value.tzinfo is None:
            raise ValueError("value must be timezone-aware")
        normalized = value.astimezone(timezone.utc)
        return self.start_utc <= normalized < self.end_utc


def daily_window(
    *,
    anchor: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    run_hour: int = 7,
) -> CollectionWindow:
    tz = ZoneInfo(timezone_name)
    if anchor is None:
        anchor = datetime.now(tz)
    elif anchor.tzinfo is None:
        raise ValueError("anchor must be timezone-aware")
    else:
        anchor = anchor.astimezone(tz)

    run_at = datetime.combine(anchor.date(), time(run_hour, 0), tzinfo=tz)
    if anchor < run_at:
        run_at = run_at - timedelta(days=1)

    start = run_at - timedelta(hours=24)
    return CollectionWindow(
        timezone_name=timezone_name,
        run_at_local=run_at,
        start_local=start,
        end_local=run_at,
        start_utc=start.astimezone(timezone.utc),
        end_utc=run_at.astimezone(timezone.utc),
    )


def historical_natural_day_window(
    *,
    start_date: date,
    end_date_inclusive: date,
    effective_end_utc: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> CollectionWindow:
    if end_date_inclusive < start_date:
        raise ValueError("end_date_inclusive precedes start_date")
    tz = ZoneInfo(timezone_name)
    start_local = datetime.combine(start_date, time.min, tzinfo=tz)
    requested_end_local = datetime.combine(
        end_date_inclusive + timedelta(days=1), time.min, tzinfo=tz
    )
    requested_end_utc = requested_end_local.astimezone(timezone.utc)
    if effective_end_utc is None:
        effective_end_utc = min(datetime.now(timezone.utc), requested_end_utc)
    elif effective_end_utc.tzinfo is None:
        raise ValueError("effective_end_utc must be timezone-aware")
    else:
        effective_end_utc = effective_end_utc.astimezone(timezone.utc)
    if effective_end_utc > requested_end_utc:
        raise ValueError("effective_end_utc exceeds requested end")
    start_utc = start_local.astimezone(timezone.utc)
    if effective_end_utc <= start_utc:
        raise ValueError("effective_end_utc must be after window start")
    end_local = effective_end_utc.astimezone(tz)
    return CollectionWindow(
        timezone_name=timezone_name,
        run_at_local=end_local,
        start_local=start_local,
        end_local=end_local,
        start_utc=start_utc,
        end_utc=effective_end_utc,
    )


def rolling_window(
    *,
    end_utc: datetime,
    hours: int = 24,
    timezone_name: str = "Asia/Shanghai",
) -> CollectionWindow:
    if end_utc.tzinfo is None:
        raise ValueError("end_utc must be timezone-aware")
    if hours <= 0:
        raise ValueError("hours must be positive")

    tz = ZoneInfo(timezone_name)
    end_local = end_utc.astimezone(tz)
    start_local = end_local - timedelta(hours=hours)
    return CollectionWindow(
        timezone_name=timezone_name,
        run_at_local=end_local,
        start_local=start_local,
        end_local=end_local,
        start_utc=start_local.astimezone(timezone.utc),
        end_utc=end_local.astimezone(timezone.utc),
    )
