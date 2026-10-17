"""Keeping a guild event and an announcement matching the row they show."""

import logging
from datetime import datetime

import discord

log = logging.getLogger(__name__)


async def message(
    channel: discord.TextChannel,
    message_id: int,
    *,
    content: str,
    mentions: discord.AllowedMentions,
    rsvp: str | None,
) -> bool:
    """Rewrite the announcement if it has drifted; False once it is gone.

    Only a fetch notices one deleted by hand, so the id alone never counts as
    an announcement that exists. rsvp is the reaction to restore, or None
    where the row takes no more sign-ups.
    """
    try:
        found = await channel.fetch_message(message_id)
        if rsvp is not None and not any(
            str(reaction.emoji) == rsvp and reaction.me for reaction in found.reactions
        ):
            # The reaction is the only way to sign up, so put it back.
            await found.add_reaction(rsvp)
        if found.content != content:
            await found.edit(content=content, allowed_mentions=mentions)
    except discord.NotFound:
        log.info("announcement %s is gone; it will be posted again", message_id)
        return False
    except discord.HTTPException as error:
        log.warning("announcement %s not updated: %s", message_id, error)
    return True


async def event(
    guild: discord.Guild,
    event_id: int,
    *,
    name: str,
    description: str,
    starts_at: datetime,
    ends_at: datetime,
) -> bool:
    """Push the fields onto the guild event; False once it is gone or spent.

    The scheduled-events cache needs an intent we do not enable, so this
    fetches: get_scheduled_event would always miss.
    """
    try:
        found = await guild.fetch_scheduled_event(event_id)
    except discord.NotFound:
        log.info("event %s is gone; it will be created again", event_id)
        return False
    except discord.HTTPException as error:
        log.warning("event %s not fetched: %s", event_id, error)
        return True

    if found.status in (discord.EventStatus.canceled, discord.EventStatus.completed):
        # Discord has no way to reopen an event, so this one is spent.
        return False
    if found.status is not discord.EventStatus.scheduled:
        # Discord refuses edits to an event that has started.
        return True
    if (found.name, found.description or "", found.start_time, found.end_time) == (
        name,
        description,
        starts_at,
        ends_at,
    ):
        # The loop syncs every pass, so an unchanged event costs no request.
        return True

    try:
        await found.edit(name=name, description=description, start_time=starts_at, end_time=ends_at)
    except discord.HTTPException as error:
        log.warning("event %s not updated: %s", event_id, error)
    return True
