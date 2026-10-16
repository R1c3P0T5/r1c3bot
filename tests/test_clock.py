from datetime import UTC, datetime, timedelta

import pytest

from ricebot import clock


def test_now_is_utc() -> None:
    # datetime.now() without an argument returns a naive local time.
    assert clock.now().utcoffset() == timedelta(0)


def test_taipei_shifts_the_wall_clock() -> None:
    # Comparing two aware datetimes compares instants, so an unconverted value
    # would still be equal; the oracle has to be the wall clock itself.
    local = clock.taipei(datetime(2026, 10, 16, 12, 0, tzinfo=UTC))

    assert local.isoformat() == "2026-10-16T20:00:00+08:00"


def test_stamp_renders_the_epoch_second() -> None:
    assert clock.stamp(datetime(2026, 10, 16, 12, 0, tzinfo=UTC)) == "<t:1792152000:F>"


def test_stamp_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="naive"):
        clock.stamp(datetime(2026, 10, 16, 12, 0))  # noqa: DTZ001
