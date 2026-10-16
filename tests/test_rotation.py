from datetime import UTC, datetime

from ricebot.bookclub.rotation import Candidate, next_host

A, B, C = 10, 20, 30


def at(day: int) -> datetime:
    return datetime(2026, 10, day, tzinfo=UTC)


def test_nobody_in_the_role_means_no_host() -> None:
    assert next_host([]) is None


def test_the_earliest_member_hosts_the_first_session() -> None:
    candidates = [Candidate(B, joined_at=at(2)), Candidate(A, joined_at=at(1))]

    assert next_host(candidates) == A


def test_a_member_who_never_hosted_goes_before_one_who_did() -> None:
    # B joined nine days later but has never taken a turn.
    candidates = [
        Candidate(A, joined_at=at(1), last_hosted=at(20)),
        Candidate(B, joined_at=at(10)),
    ]

    assert next_host(candidates) == B


def test_the_longest_wait_wins_once_everyone_has_hosted() -> None:
    candidates = [
        Candidate(A, joined_at=at(1), last_hosted=at(20)),
        Candidate(B, joined_at=at(2), last_hosted=at(6)),
        Candidate(C, joined_at=at(3), last_hosted=at(13)),
    ]

    assert next_host(candidates) == B


def test_a_skipped_member_keeps_their_place() -> None:
    candidates = [Candidate(A, joined_at=at(1)), Candidate(B, joined_at=at(2))]

    assert next_host(candidates, skipped=[A]) == B
    # Skipping records no turn for A, so A is still first next time.
    assert next_host(candidates) == A


def test_everyone_skipping_leaves_no_host() -> None:
    candidates = [Candidate(A, joined_at=at(1))]

    assert next_host(candidates, skipped=[A]) is None


def test_a_tie_is_broken_by_user_id() -> None:
    candidates = [Candidate(B, joined_at=at(1)), Candidate(A, joined_at=at(1))]

    assert next_host(candidates) == A
