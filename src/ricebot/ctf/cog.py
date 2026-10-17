"""The CTF cog: announce the contests, and open a channel when someone joins."""

import logging
from datetime import timedelta

import aiosqlite
import discord
import httpx
from discord import app_commands
from discord.ext import commands, tasks

from ricebot import clock, permissions, settings
from ricebot.ctf import ctftime
from ricebot.store import ctf as store
from ricebot.store import settings as settings_store
from ricebot.store.settings import Key

log = logging.getLogger(__name__)

SILENT = discord.AllowedMentions.none()
# A member waiting to be let in is worth a notification.
PING_USERS = discord.AllowedMentions(everyone=False, roles=False, users=True)
# Reacting with this emoji opens the discussion channel.
RSVP = "🚩"
# CTFtime's restriction values. Open is not printed, and Casual marks a
# relaxed contest rather than a closed one.
OPEN = "Open"
CASUAL = "Casual"
RESTRICTION_LABELS = {"Academic": "限學生", "High-school": "限高中生", "Invited": "邀請制"}
NO_CATEGORY = "還沒設定 CTF 討論頻道分類，請管理員用 `/config` 設定"
NOTHING_OPEN = "現在沒有在追蹤的比賽。"
NOT_TRACKED = "找不到這場。在它的討論頻道裡執行，或用選單指定一場。"
ARCHIVED_ALREADY = "這場已經封存過了。"
BAD_NUMBER = "三個欄位都要是數字，而且在標示的範圍內。"
ANNOUNCE_POSTED = "已發布"
ANNOUNCE_MISSING = "未發布，原因在 log"
EVENT_CREATED = "已建立"
EVENT_MISSING = "未建立（已經開始，或 Discord 拒絕）"
# A reply takes 2000 characters, and a line with a link approaches a hundred.
LISTED = 15
# Discord accepts at most this many autocomplete choices.
CHOICES = 25
NO_ARCHIVE_CATEGORY = "還沒設定 CTF 封存分類，請管理員用 `/config` 設定"
# A guild event's description takes 1000 characters, markup and all.
EVENT_LIMIT = 1000
# Long enough for the write-ups to be written in the channel before it goes.
ARCHIVE_AFTER = timedelta(days=2)


def _bounded(text: str, low: float, high: float) -> float | None:
    """The number the text holds when it is inside the bounds, else None."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if low <= value <= high else None


def _reason(error: discord.HTTPException) -> str:
    """The first line of a Discord error; the rest is a JSON body."""
    return str(error).splitlines()[0][:80]


def _duration_text(span: timedelta) -> str:
    days, hours = divmod(round(span.total_seconds() / 3600), 24)
    if days and hours:
        return f"{days} 天 {hours} 小時"
    return f"{days} 天" if days else f"{hours} 小時"


def _facts(contest: store.Contest, emphasis: str = "") -> list[str]:
    """What the contest is, for the message and for the guild event alike."""
    where = f"實體（{contest.location}）" if contest.onsite else "線上"
    casual = "休閒" if contest.restrictions == CASUAL else ""
    kind = " ".join(part for part in (where, contest.format, casual) if part)
    # CTFtime counts the teams registered, so a contest announced early has 0.
    teams = f"{contest.participants} 隊" if contest.participants else ""
    span = _duration_text(contest.finishes_at - contest.starts_at)
    lines = [" ".join(p for p in (kind, f"(weight {contest.weight:.2f})", teams, span) if p)]
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


def _listed(contest: store.Contest, channel: discord.TextChannel | None) -> str:
    """One line of the list: when it starts, what it is, where it is discussed."""
    title = contest.title
    if channel is not None and contest.announce_message_id is not None:
        link = channel.get_partial_message(contest.announce_message_id).jump_url
        title = f"[{contest.title}](<{link}>)"
    where = f" <#{contest.channel_id}>" if contest.channel_id is not None else ""
    return f"`{clock.taipei(contest.starts_at):%m/%d %H:%M}` {title}{where}"


def _announce_text(contest: store.Contest) -> str:
    return f"{_summary(contest)}\n\n想打的按個 {RSVP}，我開一個討論頻道給你們。"


def _channel_text(contest: store.Contest) -> str:
    """The channel's first message: a hello, the summary, and CTFtime's blurb."""
    hello = f"{contest.title} 用的頻道開了！後續的討論和 write-up 都可以丟這裡"
    parts = [hello, _summary(contest)]
    if contest.description:
        parts.append(contest.description)
    return "\n\n".join(parts)


def _event_description(contest: store.Contest) -> str:
    """The same facts as the announcement, then as much blurb as still fits."""
    head = "\n".join([*_facts(contest), contest.url, contest.page])
    blurb = ctftime.shorten(contest.description, EVENT_LIMIT - len(head) - 2)
    return f"{head}\n\n{blurb}" if blurb else head


class TuningModal(discord.ui.Modal, title="CTF 篩選與封存"):
    """The three numbers the sweep reads, prefilled with what it reads now."""

    floor = discord.ui.Label(
        text="權重門檻（-1 到 100）",
        description="比賽的 weight 要大於這個數字；設 -1 連未評分的也收",
        component=discord.ui.TextInput(max_length=6),
    )
    lookahead = discord.ui.Label(
        text="往後看幾天（1 到 60）",
        description="看得愈遠，愈容易吃掉伺服器的 100 個活動額度",
        component=discord.ui.TextInput(max_length=2),
    )
    keep = discord.ui.Label(
        text="結束後幾天封存（0 到 60）",
        component=discord.ui.TextInput(max_length=2),
    )

    def __init__(self, cog: "CtfCog", floor: float, lookahead: timedelta, keep: timedelta) -> None:
        super().__init__()
        self.cog = cog
        self.floor.component.default = f"{floor:g}"
        self.lookahead.component.default = str(lookahead.days)
        self.keep.component.default = str(keep.days)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        floor = _bounded(self.floor.component.value, -1, 100)
        lookahead = _bounded(self.lookahead.component.value, 1, 60)
        keep = _bounded(self.keep.component.value, 0, 60)
        if floor is None or lookahead is None or keep is None:
            # All or nothing: half a setting written is worse than none.
            await interaction.response.send_message(BAD_NUMBER, ephemeral=True)
            return

        await settings_store.put(self.cog.db, Key.CTF_WEIGHT_FLOOR, f"{floor:g}")
        await settings_store.put(self.cog.db, Key.CTF_LOOKAHEAD_DAYS, f"{lookahead:g}")
        await settings_store.put(self.cog.db, Key.CTF_ARCHIVE_DAYS, f"{keep:g}")
        await interaction.response.send_message(
            f"權重門檻 **{floor:g}**，往後看 **{lookahead:g}** 天，結束 **{keep:g}** 天後封存。\n"
            "-# 下一輪掃描（最多 6 小時後）生效。",
            ephemeral=True,
        )


class CtfCog(commands.GroupCog, name="ctf", description="CTF 揪團"):
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

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        await permissions.on_error(interaction, error)

    async def _weight_floor(self) -> float:
        stored = await settings_store.get_float(self.db, Key.CTF_WEIGHT_FLOOR)
        return ctftime.WEIGHT_FLOOR if stored is None else stored

    async def _days(self, key: Key, fallback: timedelta) -> timedelta:
        """A setting kept in days, falling back to the constant it overrides."""
        stored = await settings_store.get_float(self.db, key)
        return fallback if stored is None else timedelta(days=stored)

    @app_commands.command(name="config", description="調整篩選門檻與封存時間")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def config(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            TuningModal(
                self,
                await self._weight_floor(),
                await self._days(Key.CTF_LOOKAHEAD_DAYS, ctftime.LOOKAHEAD),
                await self._days(Key.CTF_ARCHIVE_DAYS, ARCHIVE_AFTER),
            )
        )

    @app_commands.command(description="接下來追蹤中的比賽")
    @app_commands.guild_only()
    async def upcoming(self, interaction: discord.Interaction) -> None:
        contests = await store.open_contests(self.db)
        if not contests:
            await interaction.response.send_message(NOTHING_OPEN, ephemeral=True)
            return

        # Deferred: the announcement links need the channel, and that is a fetch.
        await interaction.response.defer(ephemeral=True)
        channel = await self._announce_channel(interaction.guild)
        lines = [_listed(contest, channel) for contest in contests[:LISTED]]
        if len(contests) > LISTED:
            lines.append(f"-# 另外還有 {len(contests) - LISTED} 場。")
        await interaction.followup.send("\n".join(lines), ephemeral=True, allowed_mentions=SILENT)

    @app_commands.command(description="手動公告一場比賽，不經過篩選條件")
    @app_commands.guild_only()
    @app_commands.describe(ctftime_id="CTFtime 活動頁網址末端的數字")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def announce(self, interaction: discord.Interaction, ctftime_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            listed = await ctftime.one(self.http, ctftime_id)
        except (httpx.HTTPError, ValueError) as error:
            await interaction.followup.send(f"CTFtime 讀不到：{error}", ephemeral=True)
            return
        if listed is None:
            await interaction.followup.send(f"CTFtime 上沒有 {ctftime_id} 這場。", ephemeral=True)
            return

        # Asked before inserting, so the reply can say what this changed.
        known = await store.contest(self.db, ctftime_id) is not None
        contest = await store.ensure(self.db, listed)
        await self._reconcile(interaction.guild, contest)

        saved = await store.contest(self.db, ctftime_id) or contest
        over = "\n-# 這場已經結束，下一輪會直接封存。" if saved.finishes_at <= clock.now() else ""
        await interaction.followup.send(
            f"{'這場已經在追蹤了，補上缺的部分' if known else '收進來了'} **{saved.title}**\n"
            f"{clock.stamp(saved.starts_at, 'f')} ～ {clock.stamp(saved.finishes_at, 'f')}\n"
            f"公告：{ANNOUNCE_POSTED if saved.announce_message_id else ANNOUNCE_MISSING}\n"
            f"活動：{EVENT_CREATED if saved.guild_event_id else EVENT_MISSING}{over}",
            ephemeral=True,
            allowed_mentions=SILENT,
        )

    async def _contest_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """The contests still being looked after, for the `contest` option."""
        contests = await store.open_contests(self.db)
        return [
            app_commands.Choice(
                name=f"{clock.taipei(found.starts_at):%m/%d} {found.title}"[:100],
                value=str(found.ctftime_id),
            )
            for found in contests
            if current.lower() in found.title.lower()
        ][:CHOICES]

    async def _chosen(self, contest: str | None, channel_id: int | None) -> store.Contest | None:
        """The contest a command acts on: the chosen one, or this channel's."""
        if contest is None:
            open_now = await store.open_contests(self.db)
            return next((found for found in open_now if found.channel_id == channel_id), None)
        try:
            return await store.contest(self.db, int(contest))
        except ValueError:
            return None

    @app_commands.command(description="手動封存一場比賽的討論頻道")
    @app_commands.guild_only()
    @app_commands.describe(contest="哪一場，不給就是現在這個頻道")
    @app_commands.autocomplete(contest=_contest_choices)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def archive(self, interaction: discord.Interaction, contest: str | None = None) -> None:
        found = await self._chosen(contest, interaction.channel_id)
        if found is None:
            await interaction.response.send_message(NOT_TRACKED, ephemeral=True)
            return
        if found.archived_at is not None:
            await interaction.response.send_message(ARCHIVED_ALREADY, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        reason = await self._archive(interaction.guild, found)
        done = (
            "這場沒有討論頻道，直接記成封存。"
            if found.channel_id is None
            else f"**{found.title}** 的頻道封存了。"
        )
        await interaction.followup.send(reason or done, ephemeral=True, allowed_mentions=SILENT)

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
        lookahead = await self._days(Key.CTF_LOOKAHEAD_DAYS, ctftime.LOOKAHEAD)

        try:
            listed = await ctftime.upcoming(self.http, now=now, within=lookahead)
        except (httpx.HTTPError, ValueError) as error:
            # A CTFtime outage is not ours to fix; the next pass asks again.
            log.warning("CTFtime not read: %s", error)
            listed = []
        wanted = ctftime.wanted(
            listed, now=now, within=lookahead, weight_floor=await self._weight_floor()
        )
        for found in wanted:
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

        keep = await self._days(Key.CTF_ARCHIVE_DAYS, ARCHIVE_AFTER)
        for contest in await store.finished(self.db, now):
            try:
                await self._wrap_up(guild, contest, keep)
            except Exception:
                log.exception("contest %s not wrapped up", contest.ctftime_id)

        for contest in await store.finished(self.db, now - keep):
            try:
                reason = await self._archive(guild, contest)
                if reason is not None:
                    await self._archive_failed(guild, contest, reason)
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

    async def _rsvp_failed(self, guild: discord.Guild, member: discord.Member, reason: str) -> None:
        """Say that a 🚩 did not get the member in; a reaction has no reply of its own."""
        channel = await self._announce_channel(guild)
        if channel is None:
            return
        await channel.send(
            f"{member.mention} 我看到你的 🚩 了，可是頻道開不起來 🥲\n-# {reason}",
            allowed_mentions=PING_USERS,
        )

    async def _archive_failed(
        self, guild: discord.Guild, contest: store.Contest, reason: str
    ) -> None:
        """Say once that a channel cannot be put away; the sweep retries every pass."""
        if contest.archive_warned_at is not None:
            return
        channel = await self._announce_channel(guild)
        if channel is None:
            return
        await channel.send(
            f"**{contest.title}** 的討論頻道想收起來，但我搬不動他 QQ\n-# {reason}",
            allowed_mentions=SILENT,
        )
        # Recorded after sending: a repeated warning beats a silenced one.
        await store.warn_archive(self.db, contest.ctftime_id, clock.now())

    async def _wrap_up(self, guild: discord.Guild, contest: store.Contest, keep: timedelta) -> None:
        """Tell the channel the contest is over and when it closes, once."""
        if contest.finish_notice_at is not None or contest.channel_id is None:
            return
        channel = guild.get_channel(contest.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        # Claimed before sending, so a failure retries instead of repeating.
        await store.set_finish_notice(self.db, contest.ctftime_id, clock.now())
        closes = clock.taipei(contest.finishes_at + keep)
        try:
            await channel.send(
                f"比賽結束！辛苦了🙌\n這個頻道會在 {closes:%m/%d} 收起來，但內容都還會在",
                allowed_mentions=SILENT,
            )
        except discord.HTTPException as error:
            log.warning("contest %s not wrapped up: %s", contest.ctftime_id, error)
            await store.set_finish_notice(self.db, contest.ctftime_id, None)

    async def _team_channel(
        self, guild: discord.Guild, contest: store.Contest, member: discord.Member
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
            await self._rsvp_failed(guild, member, NO_CATEGORY)
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
            await self._rsvp_failed(guild, member, f"Discord 回報 {_reason(error)}")
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
        channel = await self._team_channel(member.guild, contest, member)
        if channel is None:
            return

        # Already in: a second press must not announce them again.
        known = channel.overwrites_for(member).view_channel is True
        try:
            await channel.set_permissions(member, view_channel=True)
        except discord.HTTPException as error:
            log.warning("%s not let into %s: %s", member.id, channel.id, error)
            await self._rsvp_failed(member.guild, member, f"Discord 回報 {_reason(error)}")
            return
        if not known:
            await channel.send(
                f"{member.mention} 也來一起打了！",
                allowed_mentions=PING_USERS,
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
            return

        await channel.send(f"{member.mention} 不打了 ... 掰掰", allowed_mentions=SILENT)

    async def _archive(self, guild: discord.Guild, contest: store.Contest) -> str | None:
        """Move the channel out of the way and make it read-only.

        Returns why it did not happen, or None once it has: the caller decides
        who hears about a failure.
        """
        channel = guild.get_channel(contest.channel_id) if contest.channel_id is not None else None
        if not isinstance(channel, discord.TextChannel):
            await store.archive(self.db, contest.ctftime_id, clock.now())
            return None

        category = await settings.channel(
            self.db, guild, Key.CTF_ARCHIVE_CATEGORY, discord.CategoryChannel
        )
        if category is None:
            return NO_ARCHIVE_CATEGORY

        if contest.archive_warned_at is None:
            # Said while the channel still takes messages, and only on the
            # attempt that has not already complained about failing.
            try:
                await channel.send("我要把這個頻道收起來囉", allowed_mentions=SILENT)
            except discord.HTTPException as error:
                log.warning("channel %s not told: %s", channel.id, error)

        try:
            # Member overwrites stay, so whoever was in it still reads it.
            await channel.edit(category=category)
            await channel.set_permissions(
                guild.default_role, view_channel=False, send_messages=False
            )
        except discord.HTTPException as error:
            log.warning("channel %s not archived: %s", channel.id, error)
            return f"Discord 回報 {_reason(error)}"

        await store.archive(self.db, contest.ctftime_id, clock.now())
        log.info("channel %s archived for contest %s", channel.id, contest.ctftime_id)
        return None
