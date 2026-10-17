"""When a session starts, and when its reminders come due."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from ricebot.clock import TAIPEI

START = time(20, 0)
DURATION = timedelta(hours=2)
# How late a reminder may still be sent, which is how long an outage can last
# without losing one.
CATCH_UP = timedelta(days=1)


class Reminder(StrEnum):
    """The kinds recorded in bookclub_reminders.

    Named by purpose, not by offset: the kind is part of the idempotence key,
    so a name carrying its own timing could not be retimed without the records
    of what was already sent ceasing to match.
    """

    REMIND = "remind"
    STARTING = "starting"
    FOLLOWUP = "followup"


# Offset from the session start; the follow-up lands after it ends. The
# sign-up form is not here: it is posted when the session is scheduled.
DEFAULT_OFFSETS: Mapping[Reminder, timedelta] = {
    Reminder.REMIND: -timedelta(days=1),
    Reminder.STARTING: -timedelta(hours=1),
    Reminder.FOLLOWUP: DURATION,
}


def starts_at(day: date, at: time = START) -> datetime:
    """The UTC instant a session beginning at that local time starts."""
    return datetime.combine(day, at, tzinfo=TAIPEI).astimezone(UTC)


def parse(day: str, at: str) -> datetime | None:
    """The start the two strings name, or None if either is not a date or a time."""
    try:
        return starts_at(date.fromisoformat(day), time.fromisoformat(at))
    except ValueError:
        return None


def upcoming_days(today: date, span: int) -> list[date]:
    """Today and the days after it, as many as span asks for."""
    return [today + timedelta(days=n) for n in range(span)]


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


def due(
    start: datetime,
    now: datetime,
    offsets: Mapping[Reminder, timedelta] = DEFAULT_OFFSETS,
) -> list[Reminder]:
    """The reminders that have come round and not yet gone stale, in order.

    Each one is superseded by the next, so a tick arriving after the next is
    due skips it: an outage must not replay a session's whole run of reminders
    at once. The last one holds for the catch-up window instead.
    """
    times = reminders(start, offsets)
    if not times:
        return []
    order = sorted(times, key=times.__getitem__)
    expiry = [times[kind] for kind in order[1:]] + [times[order[-1]] + CATCH_UP]
    return [kind for kind, ends in zip(order, expiry, strict=True) if times[kind] <= now < ends]


def pending_from(
    now: datetime, offsets: Mapping[Reminder, timedelta] = DEFAULT_OFFSETS
) -> datetime:
    """The earliest start whose reminders may still be unsent.

    A session is done once its last reminder is due, so CATCH_UP is how long
    a restart can still make up for what the downtime missed.
    """
    return now - max(offsets.values()) - CATCH_UP
