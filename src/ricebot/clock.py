"""The only module that reads the clock."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def now() -> datetime:
    """The current time, in UTC and tz-aware."""
    return datetime.now(UTC)


def taipei(moment: datetime) -> datetime:
    """Convert to Asia/Taipei, for display only."""
    return moment.astimezone(TAIPEI)


def stamp(moment: datetime, style: str = "F") -> str:
    """Render a Discord timestamp, which each viewer sees in their own timezone."""
    if moment.tzinfo is None:
        # A naive timestamp() silently assumes the host's timezone.
        raise ValueError(f"naive datetime: {moment}")
    return f"<t:{int(moment.timestamp())}:{style}>"
