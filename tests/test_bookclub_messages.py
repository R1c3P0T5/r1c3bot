from datetime import UTC, date, datetime

from ricebot.bookclub import messages
from ricebot.store.bookclub import Session

EIGHT_PM = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # 20:00 Taipei


def session(**fields) -> Session:
    return Session(id=1, starts_at=EIGHT_PM, **fields)


def test_an_unassigned_host_is_named_rather_than_mentioned() -> None:
    # A missing id rendering as <@None> would ping nobody and read as a fault.
    assert messages.mention(None) == "未指派"
    assert messages.mention(7) == "<@7>"


def test_the_picker_names_the_weekday_of_the_date() -> None:
    # 17 October 2026 is a Saturday; an off-by-one here mislabels every date.
    assert messages.day_choice(date(2026, 10, 17)) == "10/17（週六）"


def test_a_long_topic_is_cut_out_of_the_event_name() -> None:
    # Discord refuses a name over 100 characters, and the prefix takes some.
    assert messages.event_name("超" * 200) == "讀書會：" + "超" * 80


def test_an_event_with_no_topic_is_named_after_the_club() -> None:
    assert messages.event_name(None) == "讀書會"


def test_a_cancelled_session_stops_inviting_sign_ups() -> None:
    # The open branch running for a cancelled session would keep members
    # signing up for something that will not happen.
    assert messages.RSVP not in messages.announce(session(cancelled_at=EIGHT_PM), role_id=9)
    assert messages.RSVP in messages.announce(session(), role_id=9)


def test_the_role_is_mentioned_only_once_it_is_set() -> None:
    # An unset role would otherwise head the announcement with <@&None>.
    assert messages.announce(session(), role_id=9).startswith("<@&9>\n")
    assert "<@&" not in messages.announce(session(), role_id=None)


def test_the_event_description_leaves_out_what_it_does_not_know() -> None:
    # "主持人：None" on the guild calendar is the fault here.
    assert messages.event_description(None, "密碼學") == "主題：密碼學"
    assert messages.event_description("yuto", None) == "主持人：yuto"


def test_a_roll_call_with_nobody_on_it_lists_nobody() -> None:
    assert "報名的有" not in messages.roll_call([])
    assert messages.roll_call([7, 8]) == "報名的有 <@7> <@8>，到時候見。"


def test_a_cancelled_session_stays_marked_in_the_history() -> None:
    line = messages.history_line(session(cancelled_at=EIGHT_PM, topic="side channel"))

    assert line == "`2026/10/16` 未指派 side channel（已取消）"
