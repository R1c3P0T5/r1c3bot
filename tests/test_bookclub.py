from datetime import UTC, datetime

from ricebot.bookclub.schedule import Reminder
from ricebot.store import bookclub

A, B = 10, 20


def at(day: int) -> datetime:
    return datetime(2026, 10, day, 12, 0, tzinfo=UTC)


async def test_ensure_returns_the_same_row_twice(store) -> None:
    first = await bookclub.ensure(store, at(16))
    second = await bookclub.ensure(store, at(16))

    assert second.id == first.id


async def test_assigning_a_host_spends_their_turn(store) -> None:
    created = await bookclub.ensure(store, at(16))

    await bookclub.assign_host(store, created.id, A)
    found = await bookclub.session(store, at(16))

    assert (found.host_user_id, found.rotation_user_id) == (A, A)


async def test_a_swap_leaves_the_spent_turn_alone(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.assign_host(store, created.id, A)

    await bookclub.swap_host(store, created.id, B)
    found = await bookclub.session(store, at(16))

    # B hosts, but the turn stays spent on A, so B keeps their place in line.
    assert (found.host_user_id, found.rotation_user_id) == (B, A)


async def test_last_hosted_follows_the_rotation_not_the_host(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.assign_host(store, created.id, A)
    await bookclub.swap_host(store, created.id, B)

    assert await bookclub.last_hosted(store) == {A: at(16)}


async def test_a_cancelled_session_spends_nobodys_turn(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.assign_host(store, created.id, A)

    await bookclub.cancel(store, created.id, at(15))

    assert await bookclub.last_hosted(store) == {}


async def test_only_the_latest_turn_counts(store) -> None:
    for day in (16, 30):
        created = await bookclub.ensure(store, at(day))
        await bookclub.assign_host(store, created.id, A)

    assert await bookclub.last_hosted(store) == {A: at(30)}


async def test_a_reminder_is_claimed_once(store) -> None:
    created = await bookclub.ensure(store, at(16))

    assert await bookclub.mark_reminder(store, created.id, Reminder.ANNOUNCE, at(9)) is True
    assert await bookclub.mark_reminder(store, created.id, Reminder.ANNOUNCE, at(9)) is False


async def test_releasing_a_reminder_allows_a_retry(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.mark_reminder(store, created.id, Reminder.ANNOUNCE, at(9))

    await bookclub.unmark_reminder(store, created.id, Reminder.ANNOUNCE)

    assert await bookclub.mark_reminder(store, created.id, Reminder.ANNOUNCE, at(9)) is True


async def test_kinds_are_claimed_independently(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.mark_reminder(store, created.id, Reminder.ANNOUNCE, at(9))

    assert await bookclub.mark_reminder(store, created.id, Reminder.REMIND, at(15)) is True


async def test_a_skip_is_recorded_once(store) -> None:
    created = await bookclub.ensure(store, at(16))

    await bookclub.record_skip(store, created.id, A)
    await bookclub.record_skip(store, created.id, A)

    assert await bookclub.skipped(store, created.id) == {A}
