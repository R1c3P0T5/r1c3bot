"""Book club sessions, turns and reminder records."""

from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from ricebot.bookclub.schedule import Reminder


@dataclass(frozen=True, slots=True)
class Session:
    id: int
    starts_at: datetime
    host_user_id: int | None = None
    rotation_user_id: int | None = None
    topic: str | None = None
    event_id: int | None = None
    announce_message_id: int | None = None
    cancelled_at: datetime | None = None


def _moment(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _session(row: aiosqlite.Row) -> Session:
    return Session(
        id=row["id"],
        starts_at=datetime.fromisoformat(row["starts_at_utc"]),
        host_user_id=row["host_user_id"],
        rotation_user_id=row["rotation_user_id"],
        topic=row["topic"],
        event_id=row["event_id"],
        announce_message_id=row["announce_message_id"],
        cancelled_at=_moment(row["cancelled_at"]),
    )


async def session(db: aiosqlite.Connection, starts_at: datetime) -> Session | None:
    async with db.execute(
        "SELECT * FROM sessions WHERE starts_at_utc = ?", (starts_at.isoformat(),)
    ) as cursor:
        row = await cursor.fetchone()
    return None if row is None else _session(row)


async def next_session(db: aiosqlite.Connection, not_before: datetime) -> Session | None:
    """The earliest session that has not finished, ignoring cancelled ones.

    The caller subtracts the duration from now, so a session in progress is
    still the next one.
    """
    async with db.execute(
        "SELECT * FROM sessions WHERE starts_at_utc >= ? AND cancelled_at IS NULL"
        " ORDER BY starts_at_utc LIMIT 1",
        (not_before.isoformat(),),
    ) as cursor:
        row = await cursor.fetchone()
    return None if row is None else _session(row)


async def upcoming(
    db: aiosqlite.Connection, not_before: datetime, limit: int = 25
) -> list[Session]:
    """Sessions not yet finished, earliest first. The limit is Discord's."""
    async with db.execute(
        "SELECT * FROM sessions WHERE starts_at_utc >= ? AND cancelled_at IS NULL"
        " ORDER BY starts_at_utc LIMIT ?",
        (not_before.isoformat(), limit),
    ) as cursor:
        return [_session(row) for row in await cursor.fetchall()]


async def ensure(db: aiosqlite.Connection, starts_at: datetime) -> Session:
    """The session starting then, inserting the row the first time."""
    await db.execute(
        "INSERT OR IGNORE INTO sessions (starts_at_utc) VALUES (?)", (starts_at.isoformat(),)
    )
    await db.commit()
    found = await session(db, starts_at)
    if found is None:
        raise RuntimeError(f"no session row after insert: {starts_at}")
    return found


async def assign_host(db: aiosqlite.Connection, session_id: int, user_id: int) -> None:
    """Assign the host and spend their turn, which must happen together."""
    await db.execute(
        "UPDATE sessions SET host_user_id = ?, rotation_user_id = ? WHERE id = ?",
        (user_id, user_id, session_id),
    )
    await db.commit()


async def clear_host(db: aiosqlite.Connection, session_id: int) -> None:
    """Leave the session without a host, and without a turn spent on it."""
    await db.execute(
        "UPDATE sessions SET host_user_id = NULL, rotation_user_id = NULL WHERE id = ?",
        (session_id,),
    )
    await db.commit()


async def swap_host(db: aiosqlite.Connection, session_id: int, user_id: int) -> None:
    """Hand the session to someone else, leaving the spent turn where it was."""
    await db.execute("UPDATE sessions SET host_user_id = ? WHERE id = ?", (user_id, session_id))
    await db.commit()


async def cancel(db: aiosqlite.Connection, session_id: int, at: datetime) -> None:
    """Cancel the session, which also un-spends the turn it had assigned."""
    await db.execute(
        "UPDATE sessions SET cancelled_at = ? WHERE id = ?", (at.isoformat(), session_id)
    )
    await db.commit()


async def set_event(db: aiosqlite.Connection, session_id: int, event_id: int) -> None:
    await db.execute("UPDATE sessions SET event_id = ? WHERE id = ?", (event_id, session_id))
    await db.commit()


async def set_topic(db: aiosqlite.Connection, session_id: int, topic: str) -> None:
    await db.execute("UPDATE sessions SET topic = ? WHERE id = ?", (topic, session_id))
    await db.commit()


async def record_skip(db: aiosqlite.Connection, session_id: int, user_id: int) -> None:
    """Note that this member declined, without spending their turn."""
    await db.execute(
        "INSERT OR IGNORE INTO session_skips (session_id, user_id) VALUES (?, ?)",
        (session_id, user_id),
    )
    await db.commit()


async def skipped(db: aiosqlite.Connection, session_id: int) -> set[int]:
    async with db.execute(
        "SELECT user_id FROM session_skips WHERE session_id = ?", (session_id,)
    ) as cursor:
        return {row["user_id"] for row in await cursor.fetchall()}


async def last_hosted(db: aiosqlite.Connection) -> dict[int, datetime]:
    """When each member last took a turn, by rotation rather than by who hosted."""
    async with db.execute(
        "SELECT rotation_user_id AS user_id, MAX(starts_at_utc) AS last FROM sessions"
        " WHERE rotation_user_id IS NOT NULL AND cancelled_at IS NULL"
        " GROUP BY rotation_user_id"
    ) as cursor:
        return {
            row["user_id"]: datetime.fromisoformat(row["last"]) for row in await cursor.fetchall()
        }


async def mark_reminder(
    db: aiosqlite.Connection, session_id: int, kind: Reminder, at: datetime
) -> bool:
    """Claim a reminder before sending it; False means it was already sent.

    INSERT OR IGNORE makes the check and the claim one statement, so a second
    loop pass cannot read "not sent" and send it again.
    """
    cursor = await db.execute(
        "INSERT OR IGNORE INTO bookclub_reminders (session_id, kind, sent_at) VALUES (?, ?, ?)",
        (session_id, str(kind), at.isoformat()),
    )
    await db.commit()
    return cursor.rowcount == 1


async def unmark_reminder(db: aiosqlite.Connection, session_id: int, kind: Reminder) -> None:
    """Release the claim when sending failed, so the next pass retries."""
    await db.execute(
        "DELETE FROM bookclub_reminders WHERE session_id = ? AND kind = ?",
        (session_id, str(kind)),
    )
    await db.commit()
