"""The CTF cog: announce the contests, and open a channel when someone joins."""

import logging
from datetime import timedelta

import aiosqlite
import discord
import httpx
from discord.ext import commands, tasks

from ricebot import clock
from ricebot.ctf import ctftime
from ricebot.store import ctf as store
from ricebot.store import settings
from ricebot.store.settings import Key

log = logging.getLogger(__name__)

SILENT = discord.AllowedMentions.none()
# The sign-up list: pressing it is what opens the channel.
RSVP = "🚩"
# CTFtime's restrictions. Open is every contest that gets past the filter, so
# printing it is noise; Casual says how serious it is rather than who may
# enter, and the rest decide whether a reader can enter at all.
OPEN = "Open"
CASUAL = "Casual"
LIMITED = {"Academic": "限學生", "High-school": "限高中生", "Invited": "邀請制"}


def _length(span: timedelta) -> str:
    days, hours = divmod(round(span.total_seconds() / 3600), 24)
    if days and hours:
        return f"{days} 天 {hours} 小時"
    return f"{days} 天" if days else f"{hours} 小時"


def _summary(event: store.Event) -> str:
    """The contest, as both the announcement and its own channel introduce it."""
    where = f"實體（{event.location}）" if event.onsite else "線上"
    casual = "休閒" if event.restrictions == CASUAL else ""
    kind = " ".join(part for part in (where, event.format, casual) if part)
    lines = [
        f"## {event.title}",
        f"{kind} (weight {event.weight:.2f})　{_length(event.finishes_at - event.starts_at)}",
    ]
    if event.restrictions not in {OPEN, CASUAL, ""}:
        # Its own line, because being unable to enter outranks everything else
        # on the message.
        limit = LIMITED.get(event.restrictions, event.restrictions)
        lines.append(f"**{limit}（{event.restrictions}）**")
    if event.organizers:
        lines.append(f"主辦：{event.organizers}")
    # Angle brackets so two links do not become two embeds.
    lines.append(f"[官網](<{event.url}>) ‧ [CTFtime](<{event.page}>)")
    # The times last and apart: rendered by the client they are long strings,
    # and above the facts they crowd them out. The short style drops the
    # weekday, which the day and the duration above already imply.
    lines += [
        "",
        (
            f"{clock.stamp(event.starts_at, 'f')} ～ {clock.stamp(event.finishes_at, 'f')}"
            f"（{clock.stamp(event.starts_at, 'R')}開始）"
        ),
    ]
    return "\n".join(lines)


def _announce_text(event: store.Event) -> str:
    return f"{_summary(event)}\n\n想打的按個 {RSVP}，我開一個討論頻道給你們。"


def _channel_text(event: store.Event) -> str:
    """The channel's first message: the summary, plus what CTFtime says about it."""
    return f"{_summary(event)}\n\n{event.description}" if event.description else _summary(event)


def _event_description(event: store.Event) -> str:
    return f"{event.format}　weight {event.weight:.2f}\n{event.url}\n{event.page}"


class CtfCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: aiosqlite.Connection, guild_id: int) -> None:
        self.bot = bot
        self.db = db
        self.guild_id = guild_id
        self.http = httpx.AsyncClient(timeout=20, follow_redirects=True)

    async def cog_load(self) -> None:
        self._tick.start()

    async def cog_unload(self) -> None:
        self._tick.cancel()
        await self.http.aclose()

    @tasks.loop(hours=6)
    async def _tick(self) -> None:
        """Pick up the contests CTFtime lists, then put away the ones that are over."""
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return
        now = clock.now()
        try:
            listed = await ctftime.upcoming(self.http, now=now)
        except (httpx.HTTPError, ValueError) as error:
            # A CTFtime outage is not ours to fix; the next pass asks again.
            log.warning("CTFtime not read: %s", error)
            listed = []
        for contest in ctftime.wanted(listed, now=now):
            try:
                await store.ensure(self.db, contest)
            except Exception:
                log.exception("contest %s not recorded", contest.id)
        # Everything still open, not only what this pass listed: a contest
        # that has started, or has dropped out of the window, still has an
        # announcement and an event to keep in step.
        for event in await store.open_events(self.db):
            try:
                await self._reconcile(guild, event)
            except Exception:
                log.exception("contest %s not handled", event.ctftime_id)
        for event in await store.finished(self.db, now - ctftime.ARCHIVE_AFTER):
            try:
                await self._archive(guild, event)
            except Exception:
                log.exception("contest %s not archived", event.ctftime_id)

    @_tick.before_loop
    async def _await_guild(self) -> None:
        await self.bot.wait_until_ready()

    @_tick.error
    async def _tick_failed(self, error: BaseException) -> None:
        # The loop does not restart itself, so this is the last word on it.
        log.error("the ctf loop stopped", exc_info=error)

    async def _reconcile(self, guild: discord.Guild, event: store.Event) -> None:
        """Restore what the row projects: the announcement, and the guild event.

        Sync before add, so a projection deleted by hand is replaced in this
        pass rather than the next one. The channel is not here: it belongs to
        whoever signed up, and nobody signing up means there is none to miss.
        """
        await self._sync_announce(guild, event)
        await self._sync_event(guild, event)
        await self._add_announce(guild, event)
        await self._add_event(guild, event)

    async def _channel(self, guild: discord.Guild, key: Key) -> discord.abc.GuildChannel | None:
        channel_id = await settings.get_id(self.db, key)
        channel = guild.get_channel(channel_id) if channel_id is not None else None
        if channel is None:
            log.warning("%s is not set", key)
        return channel

    async def _announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel = await self._channel(guild, Key.CTF_ANNOUNCE_CHANNEL)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _add_announce(self, guild: discord.Guild, event: store.Event) -> None:
        """Post the contest, with the reaction that opens its channel."""
        event = await store.event(self.db, event.ctftime_id) or event
        if event.announce_message_id is not None:
            return
        channel = await self._announce_channel(guild)
        if channel is None:
            return
        try:
            message = await channel.send(_announce_text(event), allowed_mentions=SILENT)
        except discord.HTTPException as error:
            log.warning("contest %s not announced: %s", event.ctftime_id, error)
            return
        # Recorded before the reaction, so failing to add it cannot cost the
        # message and leave the next pass posting a second one.
        await store.set_announce(self.db, event.ctftime_id, message.id)
        log.info("contest %s announced as %s", event.ctftime_id, message.id)
        try:
            await message.add_reaction(RSVP)
        except discord.HTTPException as error:
            log.warning("no %s on announcement %s: %s", RSVP, message.id, error)

    async def _sync_announce(self, guild: discord.Guild, event: store.Event) -> None:
        """Rewrite the announcement if CTFtime moved the contest, or forget it if it is gone."""
        if event.announce_message_id is None:
            return
        channel = await self._announce_channel(guild)
        if channel is None:
            return
        content = _announce_text(event)
        try:
            message = await channel.fetch_message(event.announce_message_id)
            if event.archived_at is None and not any(
                str(reaction.emoji) == RSVP and reaction.me for reaction in message.reactions
            ):
                await message.add_reaction(RSVP)
            if message.content != content:
                await message.edit(content=content, allowed_mentions=SILENT)
        except discord.NotFound:
            log.info("announcement %s is gone; it will be posted again", event.announce_message_id)
            await store.set_announce(self.db, event.ctftime_id, None)
        except discord.HTTPException as error:
            log.warning("announcement %s not updated: %s", event.announce_message_id, error)

    async def _add_event(self, guild: discord.Guild, event: store.Event) -> None:
        """Put the contest on the guild calendar, whether or not anyone joins."""
        event = await store.event(self.db, event.ctftime_id) or event
        if event.event_id is not None or event.starts_at <= clock.now():
            return
        try:
            created = await guild.create_scheduled_event(
                name=event.title[:100],
                description=_event_description(event),
                start_time=event.starts_at,
                end_time=event.finishes_at,
                entity_type=discord.EntityType.external,
                location=event.url[:100],
                privacy_level=discord.PrivacyLevel.guild_only,
            )
        except discord.HTTPException as error:
            log.warning("no event for contest %s: %s", event.ctftime_id, error)
            return
        await store.set_event(self.db, event.ctftime_id, created.id)
        log.info("event %s created for contest %s", created.id, event.ctftime_id)

    async def _sync_event(self, guild: discord.Guild, event: store.Event) -> None:
        """Push CTFtime's times onto the event, and forget one that is gone."""
        if event.event_id is None:
            return
        try:
            scheduled = await guild.fetch_scheduled_event(event.event_id)
        except discord.NotFound:
            log.info("event %s is gone; it will be created again", event.event_id)
            await store.set_event(self.db, event.ctftime_id, None)
            return
        except discord.HTTPException as error:
            log.warning("event %s not fetched: %s", event.event_id, error)
            return
        if scheduled.status is not discord.EventStatus.scheduled:
            # Under way or over: Discord refuses edits, and it happened.
            return
        description = _event_description(event)
        if (scheduled.name, scheduled.description or "", scheduled.start_time) == (
            event.title[:100],
            description,
            event.starts_at,
        ):
            return
        try:
            await scheduled.edit(
                name=event.title[:100],
                description=description,
                start_time=event.starts_at,
                end_time=event.finishes_at,
            )
        except discord.HTTPException as error:
            log.warning("event %s not updated: %s", event.event_id, error)

    async def _team_channel(
        self, guild: discord.Guild, event: store.Event
    ) -> discord.TextChannel | None:
        """The contest's channel, opened on demand because the first 🚩 asks for it."""
        if event.channel_id is not None:
            channel = guild.get_channel(event.channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
            log.info("channel %s is gone; it will be created again", event.channel_id)
            await store.set_channel(self.db, event.ctftime_id, None)
        category = await self._channel(guild, Key.CTF_CATEGORY)
        if not isinstance(category, discord.CategoryChannel):
            return None
        try:
            channel = await category.create_text_channel(
                ctftime.slug(event.title, f"ctf-{event.ctftime_id}"),
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True),
                },
                topic=f"{event.title} · {event.page}",
            )
        except discord.HTTPException as error:
            log.warning("no channel for contest %s: %s", event.ctftime_id, error)
            return None
        await store.set_channel(self.db, event.ctftime_id, channel.id)
        log.info("channel %s created for contest %s", channel.id, event.ctftime_id)
        await channel.send(_channel_text(event), allowed_mentions=SILENT)
        return channel

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        member = payload.member
        if member is None or member.bot or str(payload.emoji) != RSVP:
            return
        event = await store.by_message(self.db, payload.message_id)
        if event is None or event.archived_at is not None:
            return
        channel = await self._team_channel(member.guild, event)
        if channel is None:
            return
        # Already in: someone who presses twice, or whose press arrived while
        # the channel was being made, is not announced again.
        known = channel.overwrites_for(member).view_channel is True
        try:
            await channel.set_permissions(member, view_channel=True)
        except discord.HTTPException as error:
            log.warning("%s not let into %s: %s", member.id, channel.id, error)
            return
        if not known:
            await channel.send(
                f"{member.mention} 來了。", allowed_mentions=discord.AllowedMentions(users=True)
            )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != RSVP:
            return
        event = await store.by_message(self.db, payload.message_id)
        if event is None or event.channel_id is None or event.archived_at is not None:
            return
        guild = self.bot.get_guild(payload.guild_id or self.guild_id)
        channel = guild.get_channel(event.channel_id) if guild is not None else None
        member = guild.get_member(payload.user_id) if guild is not None else None
        if not isinstance(channel, discord.TextChannel) or member is None:
            return
        try:
            # Removing the overwrite rather than denying it: the member leaves
            # no trace, and rejoining is the same path as joining.
            await channel.set_permissions(member, overwrite=None)
        except discord.HTTPException as error:
            log.warning("%s not removed from %s: %s", member.id, channel.id, error)

    async def _archive(self, guild: discord.Guild, event: store.Event) -> None:
        """Move the channel out of the way and make it read-only."""
        channel = guild.get_channel(event.channel_id) if event.channel_id is not None else None
        if not isinstance(channel, discord.TextChannel):
            await store.archive(self.db, event.ctftime_id, clock.now())
            return
        category = await self._channel(guild, Key.CTF_ARCHIVE_CATEGORY)
        if not isinstance(category, discord.CategoryChannel):
            return
        try:
            # The member overwrites stay, so the people who were in it keep
            # reading it; denying send on @everyone is what they inherit.
            await channel.edit(category=category)
            await channel.set_permissions(
                guild.default_role, view_channel=False, send_messages=False
            )
        except discord.HTTPException as error:
            log.warning("channel %s not archived: %s", channel.id, error)
            return
        await store.archive(self.db, event.ctftime_id, clock.now())
        log.info("channel %s archived for contest %s", channel.id, event.ctftime_id)
