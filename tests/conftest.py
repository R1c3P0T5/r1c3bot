import aiosqlite
import pytest

from ricebot.store import db


@pytest.fixture
async def connection():
    """An in-memory database with no migrations applied."""
    async with aiosqlite.connect(":memory:") as connection:
        connection.row_factory = aiosqlite.Row
        yield connection


@pytest.fixture
async def store(connection):
    """An in-memory database with the shipped migrations applied."""
    await db.migrate(connection)
    return connection
