"""When a session starts, and when its reminders come due."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from ricebot.clock import TAIPEI

START = time(20, 0)
DURATION = timedelta(hours=2)


class Reminder(StrEnum):
    """The kinds recorded in bookclub_reminders.

    Named by purpose, not by offset: the kind is part of the idempotence key,
    so a name carrying its own timing could not be retimed without the records
    of what was already sent ceasing to match.
    """

    ANNOUNCE = "announce"
    REMIND = "remind"
    STARTING = "starting"
    FOLLOWUP = "followup"


# Offset from the session start; the follow-up lands after it ends.
DEFAULT_OFFSETS: Mapping[Reminder, timedelta] = {
    Reminder.ANNOUNCE: -timedelta(days=7),
    Reminder.REMIND: -timedelta(days=1),
    Reminder.STARTING: -timedelta(hours=1),
    Reminder.FOLLOWUP: DURATION,
}


def starts_at(day: date, at: time = START) -> datetime:
    """The UTC instant a session beginning at that local time starts."""
    return datetime.combine(day, at, tzinfo=TAIPEI).astimezone(UTC)


def cutoff(now: datetime) -> datetime:
    """The start time dividing finished sessions from current ones.

    A session in progress is still current, so the boundary trails now by the
    duration.
    """
    return now - DURATION


def reminders(
    start: datetime, offsets: Mapping[Reminder, timedelta] = DEFAULT_OFFSETS
) -> dict[Reminder, datetime]:
    """When each reminder becomes due; the cog passes offsets read from settings."""
    return {kind: start + offset for kind, offset in offsets.items()}
