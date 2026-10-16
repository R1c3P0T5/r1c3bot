"""CTFtime's event list, and which of its contests are worth announcing."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

API = "https://ctftime.org/api/v1/events/"
# CTFtime asks callers to identify themselves, and the default agent is shared
# by every httpx caller in the world.
AGENT = "ricebot (+https://github.com/R1c3P0T5/r1c3bot)"
# How far ahead to look, which is also how far back a restart reaches: the
# whole window is asked for every time.
WINDOW = timedelta(days=21)
# Half of what CTFtime lists is weight 0, meaning no track record at all.
MIN_WEIGHT = 25.0
# Finals and invitationals: nobody joins these by deciding to.
CLOSED = "Prequalified"
# One CTFtime page. The window has never held anywhere near this many.
LIMIT = 100


@dataclass(frozen=True, slots=True)
class Contest:
    id: int
    title: str
    url: str
    page: str
    starts_at: datetime
    finishes_at: datetime
    weight: float
    format: str
    restrictions: str
    onsite: bool

    @property
    def duration(self) -> timedelta:
        return self.finishes_at - self.starts_at


def contest(raw: Mapping[str, Any]) -> Contest:
    """One contest from CTFtime's JSON."""
    return Contest(
        id=raw["id"],
        title=raw["title"],
        # The organiser's own site is blank for some entries; the CTFtime page
        # never is.
        url=raw.get("url") or raw["ctftime_url"],
        page=raw["ctftime_url"],
        starts_at=datetime.fromisoformat(raw["start"]),
        finishes_at=datetime.fromisoformat(raw["finish"]),
        weight=raw.get("weight") or 0.0,
        format=raw.get("format") or "",
        restrictions=raw.get("restrictions") or "",
        onsite=bool(raw.get("onsite")),
    )


def wanted(
    contests: Iterable[Contest],
    *,
    now: datetime,
    within: timedelta = WINDOW,
    min_weight: float = MIN_WEIGHT,
) -> list[Contest]:
    """The online, enterable contests starting inside the window, earliest first.

    Asked of the whole window every time rather than of what has appeared
    since the last look: there is then no cursor to be stale after an outage,
    and a contest added to CTFtime late is picked up like any other.
    """
    return sorted(
        (
            found
            for found in contests
            if not found.onsite
            and found.weight >= min_weight
            and found.restrictions != CLOSED
            and now < found.starts_at <= now + within
        ),
        key=lambda found: (found.starts_at, found.id),
    )


async def upcoming(
    client: httpx.AsyncClient, *, now: datetime, within: timedelta = WINDOW
) -> list[Contest]:
    """Everything CTFtime lists for the window, unfiltered."""
    response = await client.get(
        API,
        params={
            "limit": LIMIT,
            "start": int(now.timestamp()),
            "finish": int((now + within).timestamp()),
        },
        headers={"User-Agent": AGENT},
    )
    response.raise_for_status()
    return [contest(raw) for raw in response.json()]
