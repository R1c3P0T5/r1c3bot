"""Session and reminder times for the biweekly book club."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from ricebot.clock import TAIPEI

START = time(20, 0)
DURATION = timedelta(hours=2)
PERIOD = timedelta(days=14)


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


def start_of(anchor: date, index: int) -> datetime:
    """The UTC start of the session `index` periods after the anchor."""
    local = datetime.combine(anchor + index * PERIOD, START, tzinfo=TAIPEI)
    return local.astimezone(UTC)


def current_or_next(anchor: date, moment: datetime) -> tuple[int, datetime]:
    """The index and UTC start of the session in progress, or else the next one."""
    index = max(0, (moment - start_of(anchor, 0)) // PERIOD)
    # Integer division is off by one around a boundary; walking is not.
    while start_of(anchor, index) + DURATION <= moment:
        index += 1
    return index, start_of(anchor, index)


def reminders(
    start: datetime, offsets: Mapping[Reminder, timedelta] = DEFAULT_OFFSETS
) -> dict[Reminder, datetime]:
    """When each reminder becomes due; the cog passes offsets read from settings."""
    return {kind: start + offset for kind, offset in offsets.items()}
