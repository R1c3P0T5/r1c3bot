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


async def test_there_is_no_next_session_in_an_empty_schedule(store) -> None:
    assert await bookclub.next_session(store, at(16)) is None


async def test_the_next_session_is_the_earliest_one_still_ahead(store) -> None:
    for day in (30, 16, 2):
        await bookclub.ensure(store, at(day))

    found = await bookclub.next_session(store, at(10))

    # Day 2 is behind not_before, so the answer is 16, not the first row.
    assert found.starts_at == at(16)


async def test_a_cancelled_session_is_not_the_next_one(store) -> None:
    cancelled = await bookclub.ensure(store, at(16))
    await bookclub.ensure(store, at(30))
    await bookclub.cancel(store, cancelled.id, at(15))

    found = await bookclub.next_session(store, at(10))

    assert found.starts_at == at(30)


async def test_upcoming_is_ordered_by_start(store) -> None:
    for day in (30, 16, 23):
        await bookclub.ensure(store, at(day))

    found = await bookclub.upcoming(store, at(10))

    assert [s.starts_at for s in found] == [at(16), at(23), at(30)]


async def test_upcoming_omits_finished_and_cancelled_sessions(store) -> None:
    await bookclub.ensure(store, at(2))
    cancelled = await bookclub.ensure(store, at(16))
    await bookclub.ensure(store, at(30))
    await bookclub.cancel(store, cancelled.id, at(15))

    found = await bookclub.upcoming(store, at(10))

    assert [s.starts_at for s in found] == [at(30)]


async def test_assigning_a_host_spends_their_turn(store) -> None:
    created = await bookclub.ensure(store, at(16))

    await bookclub.assign_host(store, created.id, A)
    found = await bookclub.session(store, at(16))

    assert (found.host_user_id, found.rotation_user_id) == (A, A)


async def test_clearing_the_host_un_spends_the_turn(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.assign_host(store, created.id, A)

    await bookclub.clear_host(store, created.id)

    # Nobody hosts and nobody's turn was used, so A stays first in line.
    assert await bookclub.last_hosted(store) == {}


async def test_clearing_the_event_leaves_the_session(store) -> None:
    created = await bookclub.ensure(store, at(16))
    await bookclub.set_event(store, created.id, 999)

    await bookclub.clear_event(store, created.id)
    found = await bookclub.session(store, at(16))

    assert (found.event_id, found.starts_at) == (None, at(16))


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


async def test_skips_accumulate_across_a_session(store) -> None:
    created = await bookclub.ensure(store, at(16))

    await bookclub.record_skip(store, created.id, A)
    await bookclub.record_skip(store, created.id, B)

    # The whole set, not the latest one: returning only B would put A back
    # among the candidates, and A has the earliest turn, so the second skip
    # would hand the session straight back to A.
    assert await bookclub.skipped(store, created.id) == {A, B}


async def test_skips_are_scoped_to_their_session(store) -> None:
    first = await bookclub.ensure(store, at(16))
    second = await bookclub.ensure(store, at(30))
    await bookclub.record_skip(store, first.id, A)

    assert await bookclub.skipped(store, second.id) == set()
