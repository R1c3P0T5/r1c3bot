"""The numbers the CTF sweep reads, and the range /ctf config may set them to."""

from dataclasses import dataclass
from datetime import timedelta

# A contest must weigh strictly more; 0 means CTFtime has no weight for it.
WEIGHT_FLOOR = 0.0
# How far ahead contests are listed.
LOOKAHEAD = timedelta(days=21)
# Long enough for the write-ups to be written in the channel before it goes.
ARCHIVE_AFTER = timedelta(days=2)

# What /ctf config accepts, each end included. Its labels are built from
# these, so a bound cannot drift from the range printed beside it.
FLOOR_BOUNDS = (-1.0, 100.0)
LOOKAHEAD_BOUNDS = (1.0, 60.0)
KEEP_BOUNDS = (0.0, 60.0)


@dataclass(frozen=True, slots=True)
class Tuning:
    """The three numbers /ctf config submits together, in the units it shows."""

    weight_floor: float
    lookahead_days: float
    keep_days: float


def bounds_text(bounds: tuple[float, float]) -> str:
    """A range as a label states it."""
    low, high = bounds
    return f"{low:g} 到 {high:g}"


def _bounded(text: str, bounds: tuple[float, float]) -> float | None:
    """The number the text holds when it is inside the bounds, else None.

    float() accepts nan and inf, and no comparison admits either, so both
    fall out here rather than reaching a setting.
    """
    try:
        value = float(text)
    except ValueError:
        return None
    low, high = bounds
    return value if low <= value <= high else None


def parse(floor: str, lookahead: str, keep: str) -> Tuning | None:
    """The three typed numbers, or None unless every one of them is in bounds.

    All or nothing: half a setting written is worse than none.
    """
    weight_floor = _bounded(floor, FLOOR_BOUNDS)
    lookahead_days = _bounded(lookahead, LOOKAHEAD_BOUNDS)
    keep_days = _bounded(keep, KEEP_BOUNDS)
    if weight_floor is None or lookahead_days is None or keep_days is None:
        return None
    return Tuning(weight_floor, lookahead_days, keep_days)
