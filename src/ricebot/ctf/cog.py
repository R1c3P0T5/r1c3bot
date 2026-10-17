"""The CTF cog: announce the contests, and open a channel when someone joins."""

import logging
from datetime import timedelta

import aiosqlite
import discord
import httpx
from discord.ext import commands, tasks

from ricebot import clock, settings
from ricebot.ctf import ctftime
from ricebot.store import ctf as store
from ricebot.store.settings import Key

log = logging.getLogger(__name__)

SILENT = discord.AllowedMentions.none()
# Reacting with this emoji opens the discussion channel.
RSVP = "🚩"
# CTFtime's restriction values. Open is not printed, and Casual marks a
# relaxed contest rather than a closed one.
OPEN = "Open"
CASUAL = "Casual"
RESTRICTION_LABELS = {"Academic": "限學生", "High-school": "限高中生", "Invited": "邀請制"}
# A guild event's description takes 1000 characters, markup and all.
EVENT_LIMIT = 1000
# Long enough for the write-ups to be written in the channel before it goes.
ARCHIVE_AFTER = timedelta(days=2)


def _duration_text(span: timedelta) -> str:
    days, hours = divmod(round(span.total_seconds() / 3600), 24)
    if days and hours:
        return f"{days} 天 {hours} 小時"
    return f"{days} 天" if days else f"{hours} 小時"


def _facts(contest: store.Contest, emphasis: str = "") -> list[str]:
    """What the contest is, for the message and for the guild event alike."""
    # ctftime.wanted() filters onsite contests out.
    where = f"實體（{contest.location}）" if contest.onsite else "線上"
    casual = "休閒" if contest.restrictions == CASUAL else ""
    kind = " ".join(part for part in (where, contest.format, casual) if part)
    lines = [
        f"{kind} (weight {contest.weight:.2f})　{_duration_text(contest.finishes_at - contest.starts_at)}"
    ]
    if contest.restrictions not in {OPEN, CASUAL, ""}:
        # Its own line, because being unable to enter outranks everything else.
        limit = RESTRICTION_LABELS.get(contest.restrictions, contest.restrictions)
        lines.append(f"{emphasis}{limit}（{contest.restrictions}）{emphasis}")
    if contest.organizers:
        lines.append(f"主辦：{contest.organizers}")
    return lines


def _summary(contest: store.Contest) -> str:
    """The contest, as both the announcement and its own channel introduce it."""
    lines = [f"## {contest.title}", *_facts(contest, "**")]
    # Angle brackets so two links do not become two embeds.
    lines.append(f"[官網](<{contest.url}>) ‧ [CTFtime](<{contest.page}>)")
    # The times go last: the client renders each as some 60 characters, which
    # above the facts would crowd them out. The short style drops the weekday.
    lines += [
        "",
        (
            f"{clock.stamp(contest.starts_at, 'f')} ～ {clock.stamp(contest.finishes_at, 'f')}"
            f"（{clock.stamp(contest.starts_at, 'R')}開始）"
        ),
    ]
    return "\n".join(lines)


def _announce_text(contest: store.Contest) -> str:
    return f"{_summary(contest)}\n\n想打的按個 {RSVP}，我開一個討論頻道給你們。"


def _channel_text(contest: store.Contest) -> str:
    """The channel's first message: the summary, plus what CTFtime says about it."""
    return (
        f"{_summary(contest)}\n\n{contest.description}"
        if contest.description
        else _summary(contest)
    )


def _event_description(contest: store.Contest) -> str:
    """The same facts as the announcement, then as much blurb as still fits."""
    head = "\n".join([*_facts(contest), contest.url, contest.page])
    blurb = ctftime.shorten(contest.description, EVENT_LIMIT - len(head) - 2)
    return f"{head}\n\n{blurb}" if blurb else head


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
        try:
            await self._sweep()
        except Exception:
            # A failure here would stop the loop for good.
            log.exception("the ctf sweep failed")

    async def _sweep(self) -> None:
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
        for found in ctftime.wanted(listed, now=now):
            try:
                await store.ensure(self.db, found)
            except Exception:
                log.exception("contest %s not recorded", found.id)

        # Everything still open, not only what this pass listed: a contest that
        # has started still has an announcement and an event to keep in step.
        for contest in await store.open_contests(self.db):
            try:
                await self._reconcile(guild, contest)
            except Exception:
                log.exception("contest %s not handled", contest.ctftime_id)

        for contest in await store.finished(self.db, now - ARCHIVE_AFTER):
            try:
                await self._archive(guild, contest)
            except Exception:
                log.exception("contest %s not archived", contest.ctftime_id)

    @_tick.before_loop
    async def _await_guild(self) -> None:
        await self.bot.wait_until_ready()

    @_tick.error
    async def _tick_failed(self, error: BaseException) -> None:
        # The loop does not restart itself, so this is the last word on it.
        log.error("the ctf loop stopped", exc_info=error)

    async def _reconcile(self, guild: discord.Guild, contest: store.Contest) -> None:
        """Restore what the row projects: the announcement, and the guild event.

        Sync before add, so a projection deleted by hand is replaced in this
        pass rather than the next one. The channel is not here: it belongs to
        whoever signed up, and nobody signing up means there is none to miss.
        """
        await self._sync_announce(guild, contest)
        await self._sync_event(guild, contest)
        await self._add_announce(guild, contest)
        await self._add_event(guild, contest)

    async def _announce_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return await settings.channel(self.db, guild, Key.CTF_ANNOUNCE_CHANNEL, discord.TextChannel)

    async def _add_announce(self, guild: discord.Guild, contest: store.Contest) -> None:
        """Post the contest, with the reaction that opens its channel."""
        contest = await store.contest(self.db, contest.ctftime_id) or contest
        if contest.announce_message_id is not None:
            return
        channel = await self._announce_channel(guild)
        if channel is None:
            return
        try:
            message = await channel.send(_announce_text(contest), allowed_mentions=SILENT)
        except discord.HTTPException as error:
            log.warning("contest %s not announced: %s", contest.ctftime_id, error)
            return

        # Recorded before reacting, so a failed reaction cannot cause a second post.
        await store.set_announce(self.db, contest.ctftime_id, message.id)
        log.info("contest %s announced as %s", contest.ctftime_id, message.id)
        try:
            await message.add_reaction(RSVP)
        except discord.HTTPException as error:
            log.warning("no %s on announcement %s: %s", RSVP, message.id, error)

    async def _sync_announce(self, guild: discord.Guild, contest: store.Contest) -> None:
        """Rewrite the announcement if CTFtime moved the contest, or forget it if it is gone."""
        if contest.announce_message_id is None:
            return
        channel = await self._announce_channel(guild)
        if channel is None:
            return

        content = _announce_text(contest)
        try:
            message = await channel.fetch_message(contest.announce_message_id)
            if contest.archived_at is None and not any(
                str(reaction.emoji) == RSVP and reaction.me for reaction in message.reactions
            ):
                await message.add_reaction(RSVP)
            if message.content != content:
                await message.edit(content=content, allowed_mentions=SILENT)
        except discord.NotFound:
            log.info(
                "announcement %s is gone; it will be posted again", contest.announce_message_id
            )
            await store.set_announce(self.db, contest.ctftime_id, None)
        except discord.HTTPException as error:
            log.warning("announcement %s not updated: %s", contest.announce_message_id, error)

    async def _add_event(self, guild: discord.Guild, contest: store.Contest) -> None:
        """Put the contest on the guild calendar, whether or not anyone joins."""
        contest = await store.contest(self.db, contest.ctftime_id) or contest
        if contest.guild_event_id is not None or contest.starts_at <= clock.now():
            return

        try:
            created = await guild.create_scheduled_event(
                name=contest.title[:100],
                description=_event_description(contest),
                start_time=contest.starts_at,
                end_time=contest.finishes_at,
                entity_type=discord.EntityType.external,
                location=contest.url[:100],
                privacy_level=discord.PrivacyLevel.guild_only,
            )
        except discord.HTTPException as error:
            log.warning("no event for contest %s: %s", contest.ctftime_id, error)
            return

        await store.set_guild_event(self.db, contest.ctftime_id, created.id)
        log.info("event %s created for contest %s", created.id, contest.ctftime_id)

    async def _sync_event(self, guild: discord.Guild, contest: store.Contest) -> None:
        """Push CTFtime's times onto the event, and forget one that is gone."""
        if contest.guild_event_id is None:
            return
        try:
            scheduled = await guild.fetch_scheduled_event(contest.guild_event_id)
        except discord.NotFound:
            log.info("event %s is gone; it will be created again", contest.guild_event_id)
            await store.set_guild_event(self.db, contest.ctftime_id, None)
            return
        except discord.HTTPException as error:
            log.warning("event %s not fetched: %s", contest.guild_event_id, error)
            return
        if scheduled.status is not discord.EventStatus.scheduled:
            # Discord refuses edits to an event that has started.
            return

        description = _event_description(contest)
        if (scheduled.name, scheduled.description or "", scheduled.start_time) == (
            contest.title[:100],
            description,
            contest.starts_at,
        ):
            return

        try:
            await scheduled.edit(
                name=contest.title[:100],
                description=description,
                start_time=contest.starts_at,
                end_time=contest.finishes_at,
            )
        except discord.HTTPException as error:
            log.warning("event %s not updated: %s", contest.guild_event_id, error)

    async def _team_channel(
        self, guild: discord.Guild, contest: store.Contest
    ) -> discord.TextChannel | None:
        """The contest's channel, opened on demand because the first 🚩 asks for it."""
        if contest.channel_id is not None:
            channel = guild.get_channel(contest.channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
            log.info("channel %s is gone; it will be created again", contest.channel_id)
            await store.set_channel(self.db, contest.ctftime_id, None)

        category = await settings.channel(self.db, guild, Key.CTF_CATEGORY, discord.CategoryChannel)
        if category is None:
            return None

        try:
            channel = await category.create_text_channel(
                ctftime.slug(contest.title, f"ctf-{contest.ctftime_id}"),
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True),
                },
                topic=f"{contest.title} · {contest.page}",
            )
        except discord.HTTPException as error:
            log.warning("no channel for contest %s: %s", contest.ctftime_id, error)
            return None

        await store.set_channel(self.db, contest.ctftime_id, channel.id)
        log.info("channel %s created for contest %s", channel.id, contest.ctftime_id)
        await channel.send(_channel_text(contest), allowed_mentions=SILENT)
        return channel

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        member = payload.member
        if member is None or member.bot or str(payload.emoji) != RSVP:
            return
        contest = await store.by_message(self.db, payload.message_id)
        if contest is None or contest.archived_at is not None:
            return
        channel = await self._team_channel(member.guild, contest)
        if channel is None:
            return

        # Already in: a second press must not announce them again.
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
        contest = await store.by_message(self.db, payload.message_id)
        if contest is None or contest.channel_id is None or contest.archived_at is not None:
            return

        guild = self.bot.get_guild(payload.guild_id or self.guild_id)
        channel = guild.get_channel(contest.channel_id) if guild is not None else None
        member = guild.get_member(payload.user_id) if guild is not None else None
        if not isinstance(channel, discord.TextChannel) or member is None:
            return
        try:
            # Removing the overwrite leaves no trace, and rejoining repeats the
            # join path.
            await channel.set_permissions(member, overwrite=None)
        except discord.HTTPException as error:
            log.warning("%s not removed from %s: %s", member.id, channel.id, error)

    async def _archive(self, guild: discord.Guild, contest: store.Contest) -> None:
        """Move the channel out of the way and make it read-only."""
        channel = guild.get_channel(contest.channel_id) if contest.channel_id is not None else None
        if not isinstance(channel, discord.TextChannel):
            await store.archive(self.db, contest.ctftime_id, clock.now())
            return

        category = await settings.channel(
            self.db, guild, Key.CTF_ARCHIVE_CATEGORY, discord.CategoryChannel
        )
        if category is None:
            return
        try:
            # Member overwrites stay, so whoever was in it still reads it.
            await channel.edit(category=category)
            await channel.set_permissions(
                guild.default_role, view_channel=False, send_messages=False
            )
        except discord.HTTPException as error:
            log.warning("channel %s not archived: %s", channel.id, error)
            return

        await store.archive(self.db, contest.ctftime_id, clock.now())
        log.info("channel %s archived for contest %s", channel.id, contest.ctftime_id)
