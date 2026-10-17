"""Settings the community adjusts at runtime, read and written by key."""

from enum import StrEnum

import aiosqlite


class Key(StrEnum):
    """Setting names; a typo then raises AttributeError."""

    BOOKCLUB_CHANNEL = "bookclub_channel_id"
    BOOKCLUB_ROLE = "bookclub_role_id"
    BOOKCLUB_VOICE_CHANNEL = "bookclub_voice_channel_id"
    CTF_ANNOUNCE_CHANNEL = "ctf_announce_channel_id"
    CTF_CATEGORY = "ctf_category_id"
    CTF_ARCHIVE_CATEGORY = "ctf_archive_category_id"
    CTF_WEIGHT_FLOOR = "ctf_weight_floor"
    CTF_LOOKAHEAD_DAYS = "ctf_lookahead_days"
    CTF_ARCHIVE_DAYS = "ctf_archive_days"


async def get(db: aiosqlite.Connection, key: Key) -> str | None:
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
    """The setting as an int id, or None when unset."""
    value = await get(db, key)
    return None if value is None else int(value)


async def put_id(db: aiosqlite.Connection, key: Key, value: int) -> None:
    await put(db, key, str(value))


async def get_float(db: aiosqlite.Connection, key: Key) -> float | None:
    """The setting as a number, or None when unset."""
    value = await get(db, key)
    return None if value is None else float(value)
