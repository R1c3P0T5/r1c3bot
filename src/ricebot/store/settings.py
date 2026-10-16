"""Settings the community adjusts at runtime, read and written by key."""

from enum import StrEnum

import aiosqlite


class Key(StrEnum):
    """The known setting names; a typo is then an AttributeError, not a None."""

    BOOKCLUB_CHANNEL = "bookclub_channel_id"
    BOOKCLUB_VOICE_CHANNEL = "bookclub_voice_channel_id"
    CTF_ANNOUNCE_CHANNEL = "ctf_announce_channel_id"
    CTF_CATEGORY = "ctf_category_id"
    CTF_ARCHIVE_CATEGORY = "ctf_archive_category_id"


async def get(db: aiosqlite.Connection, key: Key) -> str | None:
    """Return the stored value, or None when the setting was never set."""
    async with db.execute("SELECT value FROM settings WHERE key = ?", (str(key),)) as cursor:
        row = await cursor.fetchone()
    return None if row is None else row["value"]


async def put(db: aiosqlite.Connection, key: Key, value: str) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (str(key), value),
    )
    await db.commit()


async def get_id(db: aiosqlite.Connection, key: Key) -> int | None:
    """Return a stored snowflake as an int, so it compares equal to a Discord id."""
    value = await get(db, key)
    return None if value is None else int(value)


async def put_id(db: aiosqlite.Connection, key: Key, value: int) -> None:
    await put(db, key, str(value))
