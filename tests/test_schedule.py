from datetime import UTC, date, datetime, time, timedelta

from ricebot.bookclub import schedule
from ricebot.bookclub.schedule import Reminder

FRIDAY = date(2026, 10, 16)
EIGHT_PM = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # 20:00 Taipei


def test_a_session_starts_at_eight_pm_taipei_by_default() -> None:
    assert schedule.starts_at(FRIDAY) == EIGHT_PM


def test_the_local_time_can_be_given() -> None:
    assert schedule.starts_at(FRIDAY, time(19, 30)) == datetime(2026, 10, 16, 11, 30, tzinfo=UTC)


def test_a_session_in_progress_is_still_current() -> None:
    # 21:00 Taipei, an hour into the session that started at 20:00.
    assert schedule.cutoff(datetime(2026, 10, 16, 13, 0, tzinfo=UTC)) == datetime(
        2026, 10, 16, 11, 0, tzinfo=UTC
    )


def test_reminders_bracket_the_session() -> None:
    assert schedule.reminders(EIGHT_PM) == {
        Reminder.ANNOUNCE: datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
        Reminder.REMIND: datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
        Reminder.STARTING: datetime(2026, 10, 16, 11, 0, tzinfo=UTC),
        Reminder.FOLLOWUP: datetime(2026, 10, 16, 14, 0, tzinfo=UTC),
    }


def test_offsets_override_the_defaults() -> None:
    retimed = {Reminder.ANNOUNCE: -timedelta(days=3)}

    assert schedule.reminders(EIGHT_PM, retimed) == {
        Reminder.ANNOUNCE: datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    }
