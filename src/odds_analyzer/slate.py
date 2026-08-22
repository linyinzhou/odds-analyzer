from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as fixed_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odds_analyzer.models import MatchSlateWindow


DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_START_HOUR = 12
DEFAULT_END_HOUR_NEXT_DAY = 6


def build_today_slate_window(
    target_date: date,
    timezone: str = DEFAULT_TIMEZONE,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour_next_day: int = DEFAULT_END_HOUR_NEXT_DAY,
) -> MatchSlateWindow:
    """Build the default betting-day window: afternoon today to next early morning."""

    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        if timezone != DEFAULT_TIMEZONE:
            raise
        tz = fixed_timezone(timedelta(hours=8), name=DEFAULT_TIMEZONE)
    starts_at = datetime.combine(target_date, time(hour=start_hour), tzinfo=tz)
    ends_at = datetime.combine(
        target_date + timedelta(days=1),
        time(hour=end_hour_next_day),
        tzinfo=tz,
    )
    return MatchSlateWindow(starts_at=starts_at, ends_at=ends_at, timezone=timezone)
