from datetime import UTC, datetime, timedelta

from ricebot.ctf import messages
from ricebot.store.ctf import Contest

STARTS = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # 20:00 Taipei


def contest(**fields) -> Contest:
    return Contest(
        ctftime_id=1,
        title="r1c3 CTF",
        starts_at=STARTS,
        finishes_at=STARTS + timedelta(hours=48),
        weight=25.0,
        format="Jeopardy",
        url="https://example.org",
        page="https://ctftime.org/event/1",
        **fields,
    )


def test_a_whole_number_of_days_leaves_out_the_hours() -> None:
    assert messages.duration_text(timedelta(hours=48)) == "2 天"


def test_a_span_under_a_day_is_given_in_hours() -> None:
    assert messages.duration_text(timedelta(hours=23, minutes=24)) == "23 小時"


def test_a_span_rounding_up_to_a_day_is_given_as_one() -> None:
    # 23.6 hours rounds to 24, which must read as a day and not as "0 天".
    assert messages.duration_text(timedelta(hours=23, minutes=36)) == "1 天"


def test_a_span_of_days_and_hours_names_both() -> None:
    assert messages.duration_text(timedelta(hours=36)) == "1 天 12 小時"


def test_a_contest_nobody_can_enter_says_so_on_its_own_line() -> None:
    assert messages.facts(contest(restrictions="Academic"), "**")[1] == "**限學生（Academic）**"


def test_an_unlabelled_restriction_is_shown_as_CTFtime_words_it() -> None:
    assert messages.facts(contest(restrictions="Female"))[1] == "Female（Female）"


def test_an_open_contest_gets_no_restriction_line() -> None:
    # "Open（Open）" would read as a limit where there is none.
    assert "Open" not in "\n".join(messages.facts(contest(restrictions="Open")))


def test_a_long_blurb_is_cut_down_for_the_guild_event() -> None:
    # Discord refuses a description over EVENT_LIMIT, so the blurb gives way
    # to the facts and the links rather than the other way round.
    described = messages.event_description(contest(description="字" * 5000))

    assert described.startswith("線上 Jeopardy")
    assert described.endswith("…")


def test_a_contest_with_no_announcement_is_listed_without_a_link() -> None:
    assert messages.listed(contest(), None) == "`10/16 20:00` r1c3 CTF"


def test_a_listed_contest_points_at_its_announcement_and_its_channel() -> None:
    found = contest(announce_message_id=7, channel_id=5)

    assert messages.listed(found, "https://discord.com/x") == (
        "`10/16 20:00` [r1c3 CTF](<https://discord.com/x>) <#5>"
    )


def test_the_closing_date_is_the_one_Taipei_is_on() -> None:
    # 16:30 UTC is already the next day in Taipei, and the channel closes then.
    assert "10/17" in messages.wrap_up(datetime(2026, 10, 16, 16, 30, tzinfo=UTC))
