"""Host rotation over a fixed queue."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple


@dataclass(frozen=True, slots=True)
class Host:
    """A row of the hosts queue."""

    user_id: int
    position: int
    active: bool = True


class Assignment(NamedTuple):
    user_id: int
    cursor: int


def next_host(hosts: Sequence[Host], cursor: int) -> Assignment | None:
    """Who hosts next and the cursor to store, or None when nobody can.

    The cursor advances when a session is created, so swapping a host
    afterwards leaves the rotation where it was.
    """
    # Sorted here rather than trusted from the caller: the order is the
    # rotation, so a query without ORDER BY would silently reshuffle it.
    active = sorted((h for h in hosts if h.active), key=lambda h: h.position)
    if not active:
        return None
    # Past the end of the queue the rotation wraps to the front.
    chosen = next((h for h in active if h.position >= cursor), active[0])
    return Assignment(chosen.user_id, chosen.position + 1)
