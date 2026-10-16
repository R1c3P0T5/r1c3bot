from datetime import UTC, datetime, timedelta

from ricebot.ctf import ctftime

NOW = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)

# One entry as CTFtime returned it, trimmed to the fields ricebot reads.
RAW = {
    "id": 3364,
    "title": "Securinets CTF Quals 2026",
    "ctftime_url": "https://ctftime.org/event/3364/",
    "url": "https://quals.securinets.tn/",
    "start": "2026-10-17T09:00:00+00:00",
    "finish": "2026-10-18T21:00:00+00:00",
    "weight": 85.12,
    "format": "Jeopardy",
    "restrictions": "Open",
    "onsite": False,
}


def listed(day: int, **changed: object) -> ctftime.Contest:
    """A contest starting at 09:00 on that day of October 2026."""
    return ctftime.contest(
        {
            **RAW,
            "id": day,
            "start": f"2026-10-{day:02d}T09:00:00+00:00",
            "finish": f"2026-10-{day:02d}T21:00:00+00:00",
            **changed,
        }
    )


def test_a_contest_keeps_its_times_weight_and_length() -> None:
    found = ctftime.contest(RAW)

    assert (found.id, found.title, found.weight) == (3364, "Securinets CTF Quals 2026", 85.12)
    assert found.starts_at == datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    assert found.finishes_at == datetime(2026, 10, 18, 21, 0, tzinfo=UTC)
    assert found.duration == timedelta(hours=36)


def test_the_ctftime_page_stands_in_for_a_missing_site() -> None:
    assert ctftime.contest({**RAW, "url": ""}).url == "https://ctftime.org/event/3364/"


def test_a_missing_weight_counts_as_none() -> None:
    assert ctftime.contest({**RAW, "weight": None}).weight == 0.0


def test_the_weight_threshold_is_inclusive() -> None:
    at_it, below_it = listed(20, weight=25.0), listed(21, weight=24.99)

    assert ctftime.wanted([at_it, below_it], now=NOW) == [at_it]


def test_an_onsite_contest_is_not_for_us() -> None:
    assert ctftime.wanted([listed(20, onsite=True)], now=NOW) == []


def test_a_contest_nobody_can_enter_is_left_out() -> None:
    assert ctftime.wanted([listed(20, restrictions="Prequalified")], now=NOW) == []


def test_a_contest_already_under_way_is_not_announced() -> None:
    started = listed(16, start="2026-10-17T00:00:00+00:00")

    assert ctftime.wanted([started], now=NOW) == []


def test_the_far_end_of_the_window_is_included() -> None:
    edge = listed(7, start="2026-11-07T00:00:00+00:00")
    beyond = listed(8, start="2026-11-07T00:00:01+00:00")

    assert ctftime.wanted([edge, beyond], now=NOW, within=timedelta(days=21)) == [edge]


def test_the_soonest_contest_comes_first() -> None:
    assert [
        found.id for found in ctftime.wanted([listed(30), listed(20), listed(25)], now=NOW)
    ] == [
        20,
        25,
        30,
    ]
