"""The SQLite connection and the migration runner."""

import logging
import re
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

MIGRATIONS = resources.files("ricebot.store") / "migrations"

# The filename is interpolated into SQL below, so this is also the guard.
_NAME = re.compile(r"\A\d{3}_[a-z0-9_]+\.sql\Z")


async def connect(path: Path) -> aiosqlite.Connection:
    """Open the database, apply pending migrations, and return the connection."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    # Both are per connection, and foreign_keys is off by default.
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA foreign_keys = ON")
    applied = await migrate(db)
    if applied:
        log.info("applied migrations: %s", ", ".join(applied))
    return db


async def migrate(db: aiosqlite.Connection, directory: Traversable = MIGRATIONS) -> list[str]:
    """Apply migrations not yet recorded, in filename order."""
    await db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    await db.commit()
    async with db.execute("SELECT name FROM schema_migrations") as cursor:
        done = {row["name"] for row in await cursor.fetchall()}

    applied = []
    for name, sql in _pending(directory, done):
        # The record is inside the script, so DDL and record commit together.
        try:
            await db.executescript(
                f"BEGIN;\n{sql}\nINSERT INTO schema_migrations (name) VALUES ('{name}');\nCOMMIT;"
            )
        except Exception:
            # executescript does not roll back, leaving the connection mid-transaction.
            await db.rollback()
            raise
        applied.append(name)
    return applied


def _pending(directory: Traversable, done: set[str]) -> list[tuple[str, str]]:
    files = sorted(directory.iterdir(), key=lambda f: f.name)
    for file in files:
        if not _NAME.match(file.name):
            raise ValueError(f"migration filename is not NNN_name.sql: {file.name}")
    return [(f.name, f.read_text(encoding="utf-8")) for f in files if f.name not in done]
