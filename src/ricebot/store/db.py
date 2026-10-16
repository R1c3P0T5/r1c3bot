"""The SQLite connection and the migration runner."""

import logging
import re
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

MIGRATIONS = resources.files("ricebot.store") / "migrations"

# Filenames are interpolated into SQL below, so the pattern is both the naming
# rule and the guard that keeps anything else out of a statement.
_NAME = re.compile(r"\A\d{3}_[a-z0-9_]+\.sql\Z")


async def connect(path: Path) -> aiosqlite.Connection:
    """Open the database, apply pending migrations, and return the connection."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    # WAL lets the single writer run while readers proceed; foreign_keys is off
    # by default in SQLite and must be set per connection.
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
        # executescript commits before it runs, so the script carries its own
        # transaction. Recording the name inside it keeps a half-applied
        # migration from being marked done.
        try:
            await db.executescript(
                f"BEGIN;\n{sql}\nINSERT INTO schema_migrations (name) VALUES ('{name}');\nCOMMIT;"
            )
        except Exception:
            # A failing statement aborts the script without rolling back, which
            # would leave the connection inside the transaction, seeing the
            # statements that did run.
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
