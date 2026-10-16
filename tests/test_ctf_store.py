from datetime import UTC, datetime

from ricebot.ctf.ctftime import Contest
from ricebot.store import ctf


def contest(ctftime_id: int = 3364, **changed: object) -> Contest:
    fields: dict[str, object] = {
        "id": ctftime_id,
        "title": "HITCON CTF 2026",
        "url": "https://ctf.hitcon.org/",
        "page": "https://ctftime.org/event/3400/",
        "starts_at": datetime(2026, 10, 23, 14, 0, tzinfo=UTC),
        "finishes_at": datetime(2026, 10, 25, 14, 0, tzinfo=UTC),
        "weight": 91.16,
        "format": "Jeopardy",
        "restrictions": "Open",
        "onsite": False,
    }
    return Contest(**{**fields, **changed})  # type: ignore[arg-type]


async def test_a_contest_comes_back_with_its_times(store) -> None:
    saved = await ctf.ensure(store, contest())

    assert (saved.ctftime_id, saved.title, saved.weight) == (3364, "HITCON CTF 2026", 91.16)
    assert saved.starts_at == datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
    assert saved.finishes_at == datetime(2026, 10, 25, 14, 0, tzinfo=UTC)


async def test_a_retimed_contest_keeps_what_ricebot_built(store) -> None:
    await ctf.ensure(store, contest())
    await ctf.set_announce(store, 3364, 777)
    await ctf.set_channel(store, 3364, 888)

    moved = await ctf.ensure(
        store, contest(starts_at=datetime(2026, 10, 24, 14, 0, tzinfo=UTC), weight=92.0)
    )

    assert moved.starts_at == datetime(2026, 10, 24, 14, 0, tzinfo=UTC)
    assert (moved.weight, moved.announce_message_id, moved.channel_id) == (92.0, 777, 888)


async def test_the_announcement_finds_its_contest(store) -> None:
    await ctf.ensure(store, contest())
    await ctf.set_announce(store, 3364, 777)

    found = await ctf.by_message(store, 777)

    assert found is not None and found.ctftime_id == 3364


async def test_a_reaction_on_another_message_belongs_to_nothing(store) -> None:
    await ctf.ensure(store, contest())
    await ctf.set_announce(store, 3364, 777)

    assert await ctf.by_message(store, 778) is None


async def test_an_archived_contest_is_no_longer_looked_after(store) -> None:
    await ctf.ensure(store, contest())
    await ctf.ensure(store, contest(3365))
    await ctf.archive(store, 3364, datetime(2026, 10, 26, 0, 0, tzinfo=UTC))

    assert [found.ctftime_id for found in await ctf.open_events(store)] == [3365]


async def test_a_contest_is_due_to_be_put_away_once_it_is_over(store) -> None:
    await ctf.ensure(store, contest())
    await ctf.set_channel(store, 3364, 888)

    at_the_finish = await ctf.finished(store, datetime(2026, 10, 25, 14, 0, tzinfo=UTC))
    a_second_later = await ctf.finished(store, datetime(2026, 10, 25, 14, 0, 1, tzinfo=UTC))

    assert (at_the_finish, [found.ctftime_id for found in a_second_later]) == ([], [3364])


async def test_a_contest_without_a_channel_has_nothing_to_put_away(store) -> None:
    await ctf.ensure(store, contest())

    assert await ctf.finished(store, datetime(2026, 11, 1, 0, 0, tzinfo=UTC)) == []
