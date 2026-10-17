"""CTFtime's event list, and which of its contests are worth announcing."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

_API = "https://ctftime.org/api/v1/events/"
# CTFtime asks callers to identify themselves.
_AGENT = "ricebot (+https://github.com/R1c3P0T5/r1c3bot)"
# How far ahead to look, which is also how far back a restart reaches: the
# whole window is asked for every time.
WINDOW = timedelta(days=21)
# Exclusive: a weight of 0 means CTFtime has nothing on the organizers.
MIN_WEIGHT = 0.0
# Finals and invitationals: nobody joins these by deciding to.
_CLOSED = "Prequalified"
# As much of CTFtime's description as a Discord message takes comfortably.
_BLURB_LIMIT = 1200
# One CTFtime page. The window has never held anywhere near this many.
_PAGE_LIMIT = 100

# Discord takes 100 characters; the rest leaves room for a suffix.
_NAME_LIMIT = 90


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
    location: str
    organizers: str
    participants: int
    description: str

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
        location=raw.get("location") or "",
        # Display only, so the names are joined here rather than in a table.
        organizers="、".join(o["name"] for o in raw.get("organizers") or ()),
        participants=raw.get("participants") or 0,
        description=shorten(raw.get("description") or "", _BLURB_LIMIT),
    )


def shorten(text: str, limit: int) -> str:
    """Text with CTFtime's CRLF and blank runs tidied, cut to length.

    A cut lands on a line or word break where there is one, so the result
    reads as an abbreviation.
    """
    tidy = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(tidy) <= limit:
        return tidy
    cut = tidy[:limit]
    edge = max(cut.rfind("\n"), cut.rfind(" "))
    return (cut[:edge] if edge > limit // 2 else cut).rstrip() + "…"


def slug(title: str, fallback: str) -> str:
    """A channel name for the contest, in the form Discord would rewrite it to.

    Naming it here keeps the stored name and the real one the same. The
    fallback covers a title that is all punctuation.
    """
    runs = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", title.lower())
    return runs.strip("-")[:_NAME_LIMIT].strip("-") or fallback


def wanted(
    contests: Iterable[Contest],
    *,
    now: datetime,
    within: timedelta = WINDOW,
    min_weight: float = MIN_WEIGHT,
) -> list[Contest]:
    """The enterable contests starting inside the window, earliest first.

    The whole window is asked for every time, so no cursor can go stale after
    an outage and a contest added late is picked up like any other. Onsite
    contests are left out to spare the guild's 100-event calendar.
    """
    return sorted(
        (
            found
            for found in contests
            if not found.onsite
            and found.weight > min_weight
            and found.restrictions != _CLOSED
            and now < found.starts_at <= now + within
        ),
        key=lambda found: (found.starts_at, found.id),
    )


async def upcoming(
    client: httpx.AsyncClient, *, now: datetime, within: timedelta = WINDOW
) -> list[Contest]:
    """Everything CTFtime lists for the window, unfiltered."""
    response = await client.get(
        _API,
        params={
            "limit": _PAGE_LIMIT,
            "start": int(now.timestamp()),
            "finish": int((now + within).timestamp()),
        },
        headers={"User-Agent": _AGENT},
    )
    response.raise_for_status()
    return [contest(raw) for raw in response.json()]
