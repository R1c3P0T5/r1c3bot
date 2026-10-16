from pathlib import Path

import aiosqlite
import pytest

from ricebot.store import db


async def tables(connection: aiosqlite.Connection) -> list[str]:
    async with connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ) as cursor:
        return [row["name"] for row in await cursor.fetchall()]


async def recorded(connection: aiosqlite.Connection) -> list[str]:
    async with connection.execute("SELECT name FROM schema_migrations ORDER BY name") as cursor:
        return [row["name"] for row in await cursor.fetchall()]


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


async def test_applies_migrations_in_filename_order(connection, tmp_path) -> None:
    # 010 before 002 by string order would create the child before the parent.
    write(tmp_path, "002_parent.sql", "CREATE TABLE parent (id INTEGER PRIMARY KEY);")
    write(
        tmp_path,
        "010_child.sql",
        "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id));",
    )

    applied = await db.migrate(connection, tmp_path)

    assert applied == ["002_parent.sql", "010_child.sql"]
    assert await tables(connection) == ["child", "parent", "schema_migrations"]


async def test_skips_migrations_already_recorded(connection, tmp_path) -> None:
    write(tmp_path, "001_first.sql", "CREATE TABLE first (id INTEGER PRIMARY KEY);")
    await db.migrate(connection, tmp_path)
    write(tmp_path, "002_second.sql", "CREATE TABLE second (id INTEGER PRIMARY KEY);")

    applied = await db.migrate(connection, tmp_path)

    assert applied == ["002_second.sql"]
    assert await recorded(connection) == ["001_first.sql", "002_second.sql"]


async def test_leaves_nothing_recorded_when_a_migration_fails(connection, tmp_path) -> None:
    write(
        tmp_path,
        "001_broken.sql",
        "CREATE TABLE good (id INTEGER PRIMARY KEY);\nCREATE TABLE good (id INTEGER);",
    )

    with pytest.raises(aiosqlite.OperationalError):
        await db.migrate(connection, tmp_path)

    assert await tables(connection) == ["schema_migrations"]
    assert await recorded(connection) == []


async def test_rejects_a_filename_that_does_not_sort(connection, tmp_path) -> None:
    write(tmp_path, "add_settings.sql", "CREATE TABLE settings (key TEXT PRIMARY KEY);")

    with pytest.raises(ValueError, match="add_settings.sql"):
        await db.migrate(connection, tmp_path)
