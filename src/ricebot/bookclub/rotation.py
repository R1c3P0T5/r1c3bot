"""Host rotation derived from the hosting history."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Candidate:
    """A member of the host role, with when they last took a turn."""

    user_id: int
    joined_at: datetime
    last_hosted: datetime | None = None


def next_host(candidates: Sequence[Candidate], skipped: Collection[int] = ()) -> int | None:
    """Who hosts next: whoever has gone longest without a turn.

    No cursor is stored. The order is recomputed from the history, so members
    joining, leaving or being swapped out cannot leave it stale.
    """
    eligible = [c for c in candidates if c.user_id not in skipped]
    if not eligible:
        return None
    # Never hosted comes first, then the earliest turn. The join date orders
    # those who never hosted; the user id only breaks a genuine tie.
    return min(
        eligible,
        key=lambda c: (c.last_hosted is not None, c.last_hosted or c.joined_at, c.user_id),
    ).user_id
