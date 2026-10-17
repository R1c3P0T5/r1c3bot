from datetime import UTC, date, datetime, time, timedelta

from ricebot.bookclub import schedule
from ricebot.bookclub.schedule import Reminder

FRIDAY = date(2026, 10, 16)
EIGHT_PM = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # 20:00 Taipei


def test_a_session_starts_at_eight_pm_taipei_by_default() -> None:
    assert schedule.starts_at(FRIDAY) == EIGHT_PM


def test_the_local_time_can_be_given() -> None:
    assert schedule.starts_at(FRIDAY, time(19, 30)) == datetime(2026, 10, 16, 11, 30, tzinfo=UTC)


def test_a_typed_day_and_time_become_the_start() -> None:
    assert schedule.parse("2026-10-16", "19:30") == datetime(2026, 10, 16, 11, 30, tzinfo=UTC)


def test_a_start_just_before_the_new_year_stays_in_the_old_one() -> None:
    # 00:30 Taipei on 1 January is 16:30 UTC on 31 December.
    assert schedule.parse("2026-01-01", "00:30") == datetime(2025, 12, 31, 16, 30, tzinfo=UTC)


def test_a_day_that_is_not_a_date_is_refused() -> None:
    assert schedule.parse("16/10/2026", "19:30") is None


def test_a_time_that_is_not_a_time_is_refused() -> None:
    assert schedule.parse("2026-10-16", "7pm") is None


def test_the_picker_runs_from_today_across_the_year_end() -> None:
    assert schedule.upcoming_days(date(2026, 12, 30), 4) == [
        date(2026, 12, 30),
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 1, 2),
    ]


def test_a_session_in_progress_is_still_current() -> None:
    # 21:00 Taipei, an hour into the session that started at 20:00.
    assert schedule.cutoff(datetime(2026, 10, 16, 13, 0, tzinfo=UTC)) == datetime(
        2026, 10, 16, 11, 0, tzinfo=UTC
    )


def test_reminders_bracket_the_session() -> None:
    assert schedule.reminders(EIGHT_PM) == {
        Reminder.REMIND: datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
        Reminder.STARTING: datetime(2026, 10, 16, 11, 0, tzinfo=UTC),
        Reminder.FOLLOWUP: datetime(2026, 10, 16, 14, 0, tzinfo=UTC),
    }


def test_offsets_override_the_defaults() -> None:
    retimed = {Reminder.REMIND: -timedelta(days=3)}

    assert schedule.reminders(EIGHT_PM, retimed) == {
        Reminder.REMIND: datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    }


def test_nothing_is_due_before_the_first_reminder() -> None:
    assert schedule.due(EIGHT_PM, datetime(2026, 10, 15, 11, 59, tzinfo=UTC)) == []


def test_a_reminder_is_due_the_moment_it_comes_round() -> None:
    assert schedule.due(EIGHT_PM, datetime(2026, 10, 15, 12, 0, tzinfo=UTC)) == [Reminder.REMIND]


def test_only_the_follow_up_is_left_once_the_session_is_over() -> None:
    # An hour after the session ended: the earlier two are long superseded.
    assert schedule.due(EIGHT_PM, datetime(2026, 10, 16, 15, 0, tzinfo=UTC)) == [Reminder.FOLLOWUP]


def test_a_superseded_reminder_is_skipped_rather_than_sent_late() -> None:
    # Half an hour before the start: the day-ahead nudge has been overtaken by
    # the roll call, so it is dropped rather than sent on top of it.
    assert schedule.due(EIGHT_PM, datetime(2026, 10, 16, 11, 30, tzinfo=UTC)) == [Reminder.STARTING]


def test_nothing_is_due_once_the_catch_up_window_closes() -> None:
    assert schedule.due(EIGHT_PM, datetime(2026, 10, 17, 15, 0, tzinfo=UTC)) == []


def test_a_session_stays_pending_through_the_catch_up_window() -> None:
    # The follow-up falls 2 hours after the start, and may be a day late.
    assert schedule.pending_from(datetime(2026, 10, 17, 12, 0, tzinfo=UTC)) == datetime(
        2026, 10, 16, 10, 0, tzinfo=UTC
    )
