from contextvars import ContextVar
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

viewing_zone = ContextVar("viewing_zone", default=UTC)


def zone_for(value):
    if value and len(value) <= 100:
        try:
            return ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return UTC


def today():
    return datetime.now(viewing_zone.get()).date().isoformat()
