from datetime import UTC, datetime

from ricebot.store import audit

A, B = 10, 20


def entry(day: int, user_id: int, command: str) -> audit.Entry:
    return audit.Entry(
        at=datetime(2026, 10, day, 12, 0, tzinfo=UTC),
        user_id=user_id,
        user_name="yuto",
        command=command,
        options="day=2026-10-23",
    )


async def test_an_entry_comes_back_as_it_went_in(store) -> None:
    await audit.record(store, entry(16, A, "bookclub new"))

    assert await audit.recent(store) == [entry(16, A, "bookclub new")]


async def test_the_newest_entry_comes_first(store) -> None:
    for day in (16, 2, 30):
        await audit.record(store, entry(day, A, "bookclub new"))

    assert [found.at.day for found in await audit.recent(store)] == [30, 16, 2]


async def test_the_limit_keeps_the_newest(store) -> None:
    for day in (16, 2, 30):
        await audit.record(store, entry(day, A, "bookclub new"))

    assert [found.at.day for found in await audit.recent(store, 1)] == [30]
