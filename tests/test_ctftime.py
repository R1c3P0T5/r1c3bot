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
    "location": "",
    "organizers": [{"id": 5084, "name": "Securinets"}],
    "participants": 280,
    "description": "Securinets CTF Quals 2026 is an online Jeopardy-style CTF.\r\n\r\n\r\nCategories: Web, Pwn\r\n",
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


def test_a_contest_carries_what_the_announcement_says() -> None:
    found = ctftime.contest(RAW)

    assert (found.organizers, found.participants, found.restrictions) == ("Securinets", 280, "Open")
    assert (found.onsite, found.location) == (False, "")


def test_the_description_loses_its_crlf_and_its_blank_runs() -> None:
    assert ctftime.contest(RAW).description == (
        "Securinets CTF Quals 2026 is an online Jeopardy-style CTF.\n\nCategories: Web, Pwn"
    )


def test_several_organizers_are_joined() -> None:
    raw = {**RAW, "organizers": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}

    assert ctftime.contest(raw).organizers == "A、B"


def test_a_long_description_is_cut_at_a_word_break() -> None:
    assert ctftime.shorten("one two three four", 12) == "one two…"


def test_a_description_that_fits_is_left_alone() -> None:
    assert ctftime.shorten("one two", 12) == "one two"


def test_a_cut_with_nowhere_to_break_takes_the_whole_width() -> None:
    assert ctftime.shorten("aaaaaaaaaaaaaaaa", 8) == "aaaaaaaa…"


def test_the_ctftime_page_stands_in_for_a_missing_site() -> None:
    assert ctftime.contest({**RAW, "url": ""}).url == "https://ctftime.org/event/3364/"


def test_a_missing_weight_counts_as_none() -> None:
    assert ctftime.contest({**RAW, "weight": None}).weight == 0.0


def test_an_unrated_contest_is_left_out() -> None:
    # Weight 0 is CTFtime saying it knows nothing about the organisers.
    rated, unrated = listed(20, weight=0.01), listed(21, weight=0.0)

    assert ctftime.wanted([rated, unrated], now=NOW) == [rated]


def test_the_threshold_can_be_raised_and_is_exclusive() -> None:
    at_it, above_it = listed(20, weight=25.0), listed(21, weight=25.01)

    assert ctftime.wanted([at_it, above_it], now=NOW, min_weight=25.0) == [above_it]


def test_an_onsite_contest_is_not_for_us() -> None:
    # The guild calendar is finite, and nobody plays these from home.
    assert ctftime.wanted([listed(20, onsite=True, location="Taipei, Taiwan")], now=NOW) == []


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


def test_a_title_becomes_a_channel_name() -> None:
    assert ctftime.slug("HITCON CTF 2026", "ctf") == "hitcon-ctf-2026"


def test_punctuation_runs_collapse_into_one_separator() -> None:
    assert ctftime.slug("Hack.lu CTF 2026 — Quals!", "ctf") == "hack-lu-ctf-2026-quals"


def test_a_title_that_leaves_nothing_falls_back() -> None:
    assert ctftime.slug("!!! ???", "ctf-3364") == "ctf-3364"


def test_chinese_survives_a_channel_name() -> None:
    assert ctftime.slug("臺灣 CTF 2026", "ctf") == "臺灣-ctf-2026"
