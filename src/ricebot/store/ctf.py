"""CTF contests ricebot has seen, and what it has built for each."""

from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from ricebot.ctf.ctftime import Contest
from ricebot.store import db


@dataclass(frozen=True, slots=True)
class Event:
    """A contest ricebot has seen, with the ids of what it built for it."""

    ctftime_id: int
    title: str
    starts_at: datetime
    finishes_at: datetime
    weight: float
    format: str
    url: str
    page: str
    restrictions: str = ""
    onsite: bool = False
    location: str = ""
    organizers: str = ""
    participants: int = 0
    description: str = ""
    announce_message_id: int | None = None
    channel_id: int | None = None
    event_id: int | None = None
    archived_at: datetime | None = None


def _event(row: aiosqlite.Row) -> Event:
    return Event(
        ctftime_id=row["ctftime_id"],
        title=row["title"],
        starts_at=datetime.fromisoformat(row["starts_at_utc"]),
        finishes_at=datetime.fromisoformat(row["finishes_at_utc"]),
        weight=row["weight"],
        format=row["format"],
        url=row["url"],
        page=row["page"],
        restrictions=row["restrictions"],
        onsite=bool(row["onsite"]),
        location=row["location"],
        organizers=row["organizers"],
        participants=row["participants"],
        description=row["description"],
        announce_message_id=row["announce_message_id"],
        channel_id=row["channel_id"],
        event_id=row["event_id"],
        archived_at=db.moment(row["archived_at"]),
    )


async def ensure(db: aiosqlite.Connection, contest: Contest) -> Event:
    """Record the contest, refreshing the facts CTFtime owns.

    A contest can be retimed or reweighted after it is announced, so every
    pass writes CTFtime's version of those columns and leaves ricebot's own.
    """
    await db.execute(
        "INSERT INTO ctf_events"
        " (ctftime_id, title, starts_at_utc, finishes_at_utc, weight, format, url, page,"
        " restrictions, onsite, location, organizers, participants, description)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (ctftime_id) DO UPDATE SET"
        " title = excluded.title, starts_at_utc = excluded.starts_at_utc,"
        " finishes_at_utc = excluded.finishes_at_utc, weight = excluded.weight,"
        " format = excluded.format, url = excluded.url, page = excluded.page,"
        " restrictions = excluded.restrictions, onsite = excluded.onsite,"
        " location = excluded.location, organizers = excluded.organizers,"
        " participants = excluded.participants, description = excluded.description",
        (
            contest.id,
            contest.title,
            contest.starts_at.isoformat(),
            contest.finishes_at.isoformat(),
            contest.weight,
            contest.format,
            contest.url,
            contest.page,
            contest.restrictions,
            int(contest.onsite),
            contest.location,
            contest.organizers,
            contest.participants,
            contest.description,
        ),
    )
    await db.commit()
    found = await event(db, contest.id)
    if found is None:
        raise RuntimeError(f"no ctf_events row after insert: {contest.id}")
    return found


async def event(db: aiosqlite.Connection, ctftime_id: int) -> Event | None:
    async with db.execute("SELECT * FROM ctf_events WHERE ctftime_id = ?", (ctftime_id,)) as cursor:
        row = await cursor.fetchone()
    return None if row is None else _event(row)


async def by_message(db: aiosqlite.Connection, message_id: int) -> Event | None:
    """The contest a reaction belongs to, or None when the message is not ours."""
    async with db.execute(
        "SELECT * FROM ctf_events WHERE announce_message_id = ?", (message_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return None if row is None else _event(row)


async def open_events(db: aiosqlite.Connection) -> list[Event]:
    """The contests still being looked after, soonest first."""
    async with db.execute(
        "SELECT * FROM ctf_events WHERE archived_at IS NULL ORDER BY starts_at_utc"
    ) as cursor:
        return [_event(row) for row in await cursor.fetchall()]


async def finished(db: aiosqlite.Connection, before: datetime) -> list[Event]:
    """Contests that are over and not yet put away.

    A contest nobody joined has no channel to move, but it is archived all the
    same: that is what keeps it out of what the loop looks after.
    """
    async with db.execute(
        "SELECT * FROM ctf_events WHERE archived_at IS NULL AND finishes_at_utc < ?"
        " ORDER BY finishes_at_utc",
        (before.isoformat(),),
    ) as cursor:
        return [_event(row) for row in await cursor.fetchall()]


async def set_announce(db: aiosqlite.Connection, ctftime_id: int, message_id: int | None) -> None:
    """Remember the announcement, whose reactions are the sign-up list."""
    await db.execute(
        "UPDATE ctf_events SET announce_message_id = ? WHERE ctftime_id = ?",
        (message_id, ctftime_id),
    )
    await db.commit()


async def set_channel(db: aiosqlite.Connection, ctftime_id: int, channel_id: int | None) -> None:
    """Record the discussion channel, or forget it with None so the next 🚩 opens one."""
    await db.execute(
        "UPDATE ctf_events SET channel_id = ? WHERE ctftime_id = ?", (channel_id, ctftime_id)
    )
    await db.commit()


async def set_guild_event(db: aiosqlite.Connection, ctftime_id: int, event_id: int | None) -> None:
    """Record the guild event, or forget it with None so a later pass recreates it."""
    await db.execute(
        "UPDATE ctf_events SET event_id = ? WHERE ctftime_id = ?", (event_id, ctftime_id)
    )
    await db.commit()


async def archive(db: aiosqlite.Connection, ctftime_id: int, at: datetime) -> None:
    """Note that the channel has been put away, so the sweep skips it."""
    await db.execute(
        "UPDATE ctf_events SET archived_at = ? WHERE ctftime_id = ?", (at.isoformat(), ctftime_id)
    )
    await db.commit()
