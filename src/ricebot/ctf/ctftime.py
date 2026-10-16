"""CTFtime's event list, and which of its contests are worth announcing."""

import re
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
# Exclusive, so the default keeps every rated contest and drops the unrated
# ones: a weight of 0 means CTFtime has nothing on the organisers at all, and
# that is twenty of the next thirty-six.
MIN_WEIGHT = 0.0
# Finals and invitationals: nobody joins these by deciding to.
CLOSED = "Prequalified"
# As much of CTFtime's description as a Discord message takes comfortably.
BLURB = 1200
# One CTFtime page. The window has never held anywhere near this many.
LIMIT = 100


# Long enough for the write-ups to be written in the channel before it goes.
ARCHIVE_AFTER = timedelta(days=2)
# Discord takes 100 characters; the rest leaves room for a suffix.
NAME_LIMIT = 90


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
        description=shorten(raw.get("description") or "", BLURB),
    )


def shorten(text: str, limit: int) -> str:
    """CTFtime's description, tidied and cut to length.

    Its text is CRLF with long runs of blank lines, and a cut lands on a line
    or word break where there is one: a description sliced mid-word reads like
    a bug rather than an abbreviation.
    """
    tidy = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(tidy) <= limit:
        return tidy
    cut = tidy[:limit]
    edge = max(cut.rfind("\n"), cut.rfind(" "))
    return (cut[:edge] if edge > limit // 2 else cut).rstrip() + "…"


def slug(title: str, fallback: str) -> str:
    """A channel name for the contest: Discord lowercases and rewrites the rest.

    Doing it here rather than letting Discord do it keeps the stored name and
    the real one the same, and the fallback covers a title that is all
    punctuation once the separators collapse.
    """
    runs = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", title.lower())
    return runs.strip("-")[:NAME_LIMIT].strip("-") or fallback


def wanted(
    contests: Iterable[Contest],
    *,
    now: datetime,
    within: timedelta = WINDOW,
    min_weight: float = MIN_WEIGHT,
) -> list[Contest]:
    """The enterable contests starting inside the window, earliest first.

    Asked of the whole window every time rather than of what has appeared
    since the last look: there is then no cursor to be stale after an outage,
    and a contest added to CTFtime late is picked up like any other.

    Onsite contests are left out: a guild holds 100 scheduled events and a
    busy three weeks lists two dozen contests, so the calendar is worth
    spending only on the ones anyone here can actually enter from home.
    """
    return sorted(
        (
            found
            for found in contests
            if not found.onsite
            and found.weight > min_weight
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
