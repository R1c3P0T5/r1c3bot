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

    The kind is part of the idempotence key, so each name says what the
    reminder is for and stays valid when its timing changes.
    """

    REMIND = "remind"
    STARTING = "starting"
    FOLLOWUP = "followup"


# Offset from the session start; the follow-up lands after it ends. The
# sign-up form is not here: it is posted when the session is scheduled.
OFFSETS: Mapping[Reminder, timedelta] = {
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


def reminders(start: datetime) -> dict[Reminder, datetime]:
    """When each reminder becomes due."""
    return {kind: start + offset for kind, offset in OFFSETS.items()}


def due(start: datetime, now: datetime) -> list[Reminder]:
    """The reminders that have come round and not yet gone stale, in order.

    Each one supersedes the one before, so a tick arriving late skips what it
    missed instead of replaying the whole run. The last one holds for the
    catch-up window.
    """
    times = reminders(start)
    order = sorted(times, key=times.__getitem__)
    expiry = [times[kind] for kind in order[1:]] + [times[order[-1]] + CATCH_UP]
    return [kind for kind, ends in zip(order, expiry, strict=True) if times[kind] <= now < ends]


def pending_from(now: datetime) -> datetime:
    """The earliest start whose reminders may still be unsent.

    A session is done once its last reminder is due, so CATCH_UP is how long
    a restart can still make up for what the downtime missed.
    """
    return now - max(OFFSETS.values()) - CATCH_UP
