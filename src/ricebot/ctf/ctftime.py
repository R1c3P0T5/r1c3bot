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
# Finals: only the teams that qualified enter.
_PREQUALIFIED = "Prequalified"
# The longest description kept for a Discord message.
_DESCRIPTION_LIMIT = 1200
# Contests asked for per call; the window is never paged.
_FETCH_LIMIT = 100

# Under Discord's 100-character cap for a channel name.
_SLUG_LIMIT = 90


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


def contest(raw: Mapping[str, Any]) -> Contest:
    """One contest from CTFtime's JSON."""
    return Contest(
        id=raw["id"],
        title=raw["title"],
        # Some entries leave the organizer's own site blank.
        url=raw.get("url") or raw["ctftime_url"],
        page=raw["ctftime_url"],
        starts_at=datetime.fromisoformat(raw["start"]),
        finishes_at=datetime.fromisoformat(raw["finish"]),
        weight=raw.get("weight") or 0.0,
        format=raw.get("format") or "",
        restrictions=raw.get("restrictions") or "",
        onsite=bool(raw.get("onsite")),
        location=raw.get("location") or "",
        # Display only, so one string beats a table.
        organizers="、".join(o["name"] for o in raw.get("organizers") or ()),
        participants=raw.get("participants") or 0,
        description=shorten(raw.get("description") or "", _DESCRIPTION_LIMIT),
    )


def shorten(text: str, limit: int) -> str:
    """Text with CTFtime's CRLF and blank runs tidied, cut to length.

    A cut lands on a line or word break where there is one, so the result
    reads as an abbreviation.
    """
    tidy = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(tidy) <= limit:
        return tidy
    # The ellipsis counts towards the limit, so the body gets one less.
    cut = tidy[: max(limit - 1, 0)]
    edge = max(cut.rfind("\n"), cut.rfind(" "))
    return (cut[:edge] if edge > limit // 2 else cut).rstrip() + "…"


def slug(title: str, fallback: str) -> str:
    """A channel name for the contest, in the form Discord would rewrite it to.

    Naming it here keeps the stored name and the real one the same. The
    fallback covers a title that is all punctuation.
    """
    runs = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", title.lower())
    return runs.strip("-")[:_SLUG_LIMIT].strip("-") or fallback


def wanted(
    contests: Iterable[Contest],
    *,
    now: datetime,
    within: timedelta,
    weight_floor: float,
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
            and found.weight > weight_floor
            and found.restrictions != _PREQUALIFIED
            and now < found.starts_at <= now + within
        ),
        key=lambda found: (found.starts_at, found.id),
    )


async def one(client: httpx.AsyncClient, ctftime_id: int) -> Contest | None:
    """One contest by its CTFtime id, or None when CTFtime lists no such event."""
    response = await client.get(f"{_API}{ctftime_id}/", headers={"User-Agent": _AGENT})
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return contest(response.json())


async def upcoming(client: httpx.AsyncClient, *, now: datetime, within: timedelta) -> list[Contest]:
    """Everything CTFtime lists for the window, unfiltered."""
    response = await client.get(
        _API,
        params={
            "limit": _FETCH_LIMIT,
            "start": int(now.timestamp()),
            "finish": int((now + within).timestamp()),
        },
        headers={"User-Agent": _AGENT},
    )
    response.raise_for_status()
    return [contest(raw) for raw in response.json()]
