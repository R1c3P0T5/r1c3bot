from datetime import UTC, date, datetime

from ricebot.bookclub import schedule
from ricebot.bookclub.schedule import Reminder

ANCHOR = date(2026, 10, 16)  # a Friday
ANCHOR_START = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # 20:00 Taipei


def test_the_anchor_session_starts_at_eight_pm_taipei() -> None:
    assert schedule.start_of(ANCHOR, 0) == ANCHOR_START


def test_a_session_stays_on_friday_across_the_year_boundary() -> None:
    # Both are Fridays. An ISO-week parity rule flips at the turn of the year
    # and would land on 2027-01-01 or 2027-01-15 instead.
    assert schedule.start_of(date(2026, 12, 25), 1) == datetime(2027, 1, 8, 12, 0, tzinfo=UTC)


def test_the_tenth_session_does_not_drift() -> None:
    assert schedule.start_of(ANCHOR, 10) == datetime(2027, 3, 5, 12, 0, tzinfo=UTC)


def test_a_session_in_progress_is_the_current_one() -> None:
    during = datetime(2026, 10, 16, 13, 0, tzinfo=UTC)  # 21:00 Taipei

    assert schedule.current_or_next(ANCHOR, during) == (0, ANCHOR_START)


def test_the_next_session_takes_over_the_moment_one_ends() -> None:
    ended = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)  # exactly 22:00 Taipei

    assert schedule.current_or_next(ANCHOR, ended) == (
        1,
        datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
    )


def test_before_the_anchor_the_next_session_is_the_anchor() -> None:
    early = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)

    assert schedule.current_or_next(ANCHOR, early) == (0, ANCHOR_START)


def test_reminders_bracket_the_session() -> None:
    assert schedule.reminders(ANCHOR_START) == {
        Reminder.ANNOUNCE: datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
        Reminder.REMIND_1D: datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
        Reminder.REMIND_1H: datetime(2026, 10, 16, 11, 0, tzinfo=UTC),
        Reminder.FOLLOWUP: datetime(2026, 10, 16, 14, 0, tzinfo=UTC),
    }
