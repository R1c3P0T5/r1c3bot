"""The record of who ran which command."""

from dataclasses import dataclass
from datetime import datetime

import aiosqlite


@dataclass(frozen=True, slots=True)
class Entry:
    at: datetime
    user_id: int
    user_name: str
    command: str
    options: str


async def record(db: aiosqlite.Connection, entry: Entry) -> None:
    await db.execute(
        "INSERT INTO audit_log (at_utc, user_id, user_name, command, options)"
        " VALUES (?, ?, ?, ?, ?)",
        (entry.at.isoformat(), entry.user_id, entry.user_name, entry.command, entry.options),
    )
    await db.commit()


async def recent(db: aiosqlite.Connection, limit: int = 10) -> list[Entry]:
    """The commands most recently run, newest first."""
    async with db.execute(
        "SELECT * FROM audit_log ORDER BY at_utc DESC, id DESC LIMIT ?", (limit,)
    ) as cursor:
        return [
            Entry(
                at=datetime.fromisoformat(row["at_utc"]),
                user_id=row["user_id"],
                user_name=row["user_name"],
                command=row["command"],
                options=row["options"],
            )
            for row in await cursor.fetchall()
        ]
