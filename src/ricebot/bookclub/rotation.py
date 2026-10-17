"""Host rotation derived from the hosting history."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

# The gateway can send a member without a join date, and that member waits
# behind everyone whose date is known.
_UNKNOWN_JOIN = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A member of the host role, with when they joined and last took a turn."""

    user_id: int
    joined_at: datetime | None = None
    last_hosted: datetime | None = None


def _order(candidate: Candidate) -> tuple[bool, datetime, int]:
    """Never hosted first, then the earliest turn, then the id.

    The join date orders those who never hosted; the user id only breaks a
    genuine tie.
    """
    waited_since = candidate.last_hosted or candidate.joined_at or _UNKNOWN_JOIN
    return (candidate.last_hosted is not None, waited_since, candidate.user_id)


def next_host(candidates: Sequence[Candidate], skipped: Collection[int] = ()) -> int | None:
    """Who hosts next: whoever has gone longest without a turn.

    No cursor is stored. The order is recomputed from the history, so members
    joining, leaving or being swapped out cannot leave it stale.
    """
    eligible = [c for c in candidates if c.user_id not in skipped]
    if not eligible:
        return None
    return min(eligible, key=_order).user_id
