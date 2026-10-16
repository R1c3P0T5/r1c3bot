"""The /bookclub commands."""

import logging
from datetime import date, datetime, time, timedelta

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ricebot import clock, permissions
from ricebot.bookclub import rotation, schedule
from ricebot.store import bookclub as store
from ricebot.store import settings
from ricebot.store.settings import Key

log = logging.getLogger(__name__)

SILENT = discord.AllowedMentions.none()
# The announcement is the one message the whole role should see.
NOTIFY_ROLE = discord.AllowedMentions(roles=True, users=True)
# A change of host is worth a notification; a topic or a cancellation is not.
NOTIFY = discord.AllowedMentions(users=True)
NO_ROLE = "還沒設定讀書會身分組，請管理員執行 `/bookclub role`。"
NO_SESSION = "目前沒有排定的場次，用 `/bookclub new` 排一場。"
NO_VOICE = "未建立（還沒設定讀書會語音頻道，請管理員用 `/config` 設定）"
POSTED = "已發布"
NO_CHANNEL = "未發布（還沒設定讀書會公告頻道，請管理員用 `/config` 設定）"
IN_PAST = "未建立（不能建立過去的活動，Discord 不接受）"
CREATED = "已建立"
NO_ASSIGNEE = "未指派"
EVENT_NAME = "讀書會"
# The sign-up list: the reaction is the only record of who is coming.
RSVP = "🚩"
NOT_HOST = "只有本場主持人或管理員可以這麼做。"
NO_HOST = "這場還沒有指派主持人。"
# Discord has no date picker, so the list stands in for one: 25 consecutive
# days, which is also the most it will accept in one autocomplete reply.
DAY_SPAN = 25
# Half hours from morning to the usual start. 08:00 to 20:00 inclusive is
# exactly 25 entries, which is also Discord's limit for an autocomplete reply.
TIMES = tuple(f"{t // 60:02d}:{t % 60:02d}" for t in range(8 * 60, 20 * 60 + 1, 30))
BAD_TIME = "日期要寫成 YYYY-MM-DD、時間寫成 HH:MM。"


_WEEKDAYS = "一二三四五六日"


def _weekday(day: date) -> str:
    return f"週{_WEEKDAYS[day.weekday()]}"


def _mention(user_id: int | None, fallback: str) -> str:
    return f"<@{user_id}>" if user_id is not None else fallback


def _announce_text(role_id: int | None, session: store.Session) -> str:
    """The sign-up form, which is where a session's information lives."""
    lines = [] if role_id is None else [f"<@&{role_id}>"]
    lines += [
        f"## 讀書會 {clock.stamp(session.starts_at)}",
        f"主持人：{_mention(session.host_user_id, NO_ASSIGNEE)}",
        f"主題：{session.topic or '未設定'}",
    ]
    if session.cancelled_at is not None:
        lines.append("**這場已取消。**")
    else:
        lines.append(f"按 {RSVP} 報名。活動頁面的「感興趣」不算，提醒與點名都看這裡的 {RSVP}。")
    return "\n".join(lines)


def _form_link(channel: discord.TextChannel, session: store.Session) -> str:
    """A link back to the form, so a notification need not repeat it."""
    if session.announce_message_id is None:
        return ""
    return f"\n報名表：{channel.get_partial_message(session.announce_message_id).jump_url}"


def _event_name(session: store.Session) -> str:
    # The event name is capped at 100 characters, so a long topic is trimmed.
    return f"{EVENT_NAME}：{session.topic[:80]}" if session.topic else EVENT_NAME


def _event_description(guild: discord.Guild, session: store.Session) -> str:
    lines = []
    if session.host_user_id is not None:
        member = guild.get_member(session.host_user_id)
        # An event description is plain text, so a mention would not render.
        lines.append(f"主持人：{member.display_name if member else session.host_user_id}")
    if session.topic:
        lines.append(f"主題：{session.topic}")
    return "\n".join(lines)


class BookclubCog(commands.GroupCog, name="bookclub", description="讀書會"):
    def __init__(self, bot: commands.Bot, db: aiosqlite.Connection, guild_id: int) -> None:
        self.bot = bot
        self.db = db
        self.guild_id = guild_id
        self._senders = {
            schedule.Reminder.REMIND: self._remind,
            schedule.Reminder.STARTING: self._starting,
            schedule.Reminder.FOLLOWUP: self._followup,
        }

    async def cog_load(self) -> None:
        self._tick.start()

    async def cog_unload(self) -> None:
        self._tick.cancel()

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        await permissions.on_error(interaction, error)

    async def _candidates(self, guild: discord.Guild) -> list[rotation.Candidate] | None:
        """The host role's members, or None when the role is unset or gone."""
        role_id = await settings.get_id(self.db, Key.BOOKCLUB_ROLE)
        role = guild.get_role(role_id) if role_id is not None else None
        if role is None:
            return None
        hosted = await store.last_hosted(self.db)
        return [
            rotation.Candidate(
                member.id,
                # joined_at is None only for a member the gateway sent without
                # one; treating that as "just joined" puts them last.
                joined_at=member.joined_at or clock.now(),
                last_hosted=hosted.get(member.id),
            )
            for member in role.members
            if not member.bot
        ]

    @app_commands.command(description="設定讀書會身分組：輪替名單與提醒的對象")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await settings.put_id(self.db, Key.BOOKCLUB_ROLE, role.id)
        await interaction.response.send_message(
            f"讀書會身分組設為 {role.mention}，目前 {len(role.members)} 人。",
            ephemeral=True,
            allowed_mentions=SILENT,
        )

    async def _assign_host(self, guild: discord.Guild, session: store.Session) -> int | None:
        candidates = await self._candidates(guild)
        if candidates is None:
            return None
        host = rotation.next_host(candidates, await store.skipped(self.db, session.id))
        if host is not None:
            await store.assign_host(self.db, session.id, host)
        return host

    async def _event(
        self, guild: discord.Guild, session: store.Session
    ) -> discord.ScheduledEvent | None:
        """The session's event, forgetting it when it is gone.

        Fetched rather than read from cache: the scheduled-events cache needs
        an intent we do not enable, so get_scheduled_event always misses. A
        fetch also distinguishes "deleted by hand" from "not cached".
        """
        if session.event_id is None:
            return None
        try:
            event = await guild.fetch_scheduled_event(session.event_id)
        except discord.NotFound:
            await store.set_event(self.db, session.id, None)
            return None
        except discord.HTTPException as error:
            log.warning("event %s not fetched: %s", session.event_id, error)
            return None
        if event.status in (discord.EventStatus.canceled, discord.EventStatus.completed):
            # Discord has no way to reopen an event, so this one is spent.
            await store.set_event(self.db, session.id, None)
            return None
        return event

    async def _add_event(self, guild: discord.Guild, session: store.Session) -> str:
        """Put the session on the guild calendar, and say what happened.

        The caller reports the result, so the reason has to come back with it:
        a bare None would be filled in with whichever cause seemed likeliest.
        """
        if await self._event(guild, session) is not None:
            return CREATED
        if session.starts_at <= clock.now():
            # Discord refuses an event in the past, and we can tell without
            # spending a request to be told.
            return IN_PAST
        channel_id = await settings.get_id(self.db, Key.BOOKCLUB_VOICE_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            return NO_VOICE
        try:
            event = await guild.create_scheduled_event(
                name=_event_name(session),
                description=_event_description(guild, session),
                start_time=session.starts_at,
                end_time=session.starts_at + schedule.DURATION,
                entity_type=discord.EntityType.voice,
                channel=channel,
                privacy_level=discord.PrivacyLevel.guild_only,
            )
        except discord.HTTPException as error:
            # The session is already scheduled; the event is the extra, so a
            # failure here must not fail the command.
            log.warning("no event for %s: %s", session.starts_at, error)
            return f"未建立（Discord 回報 {str(error).splitlines()[0][:80]}）"
        await store.set_event(self.db, session.id, event.id)
        return CREATED

    async def _add_announce(self, guild: discord.Guild, session: store.Session) -> str:
        """Post the sign-up form, and say what happened."""
        if session.announce_message_id is not None:
            return POSTED
        channel = await self._channel(guild)
        if channel is None:
            return NO_CHANNEL
        role_id = await settings.get_id(self.db, Key.BOOKCLUB_ROLE)
        try:
            message = await channel.send(
                _announce_text(role_id, session), allowed_mentions=NOTIFY_ROLE
            )
        except discord.HTTPException as error:
            log.warning("no announcement for %s: %s", session.starts_at, error)
            return f"未發布（Discord 回報 {str(error).splitlines()[0][:80]}）"
        # Recorded before the reaction, so failing to add it cannot cost the
        # message and leave the next pass posting a second one.
        await store.set_announce(self.db, session.id, message.id)
        try:
            await message.add_reaction(RSVP)
        except discord.HTTPException as error:
            log.warning("no %s on announcement %s: %s", RSVP, message.id, error)
        return POSTED

    async def _sync_announce(self, guild: discord.Guild, session: store.Session) -> None:
        """Rewrite the form; the row must already be current."""
        if session.announce_message_id is None:
            return
        channel = await self._channel(guild)
        if channel is None:
            return
        role_id = await settings.get_id(self.db, Key.BOOKCLUB_ROLE)
        try:
            await channel.get_partial_message(session.announce_message_id).edit(
                content=_announce_text(role_id, session), allowed_mentions=NOTIFY_ROLE
            )
        except discord.NotFound:
            # Deleted by hand; forgetting it lets the next pass post a new one.
            await store.set_announce(self.db, session.id, None)
        except discord.HTTPException as error:
            log.warning("announcement %s not updated: %s", session.announce_message_id, error)

    async def _update(
        self, interaction: discord.Interaction, session: store.Session, text: str
    ) -> None:
        """Confirm privately, and post the update in the book club channel.

        One destination for everything public, so running a command in another
        channel does not scatter a session's record across the server.
        """
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=SILENT)
        channel = await self._channel(interaction.guild)
        if channel is None:
            return
        await channel.send(f"{text}{_form_link(channel, session)}", allowed_mentions=NOTIFY)

    async def _sync(self, guild: discord.Guild, session: store.Session) -> None:
        """Push the row onto both of its projections, the event and the form.

        Re-read first: the caller holds a snapshot from before its own write.
        """
        updated = await store.session(self.db, session.starts_at)
        if updated is None:
            return
        await self._sync_event(guild, updated)
        await self._sync_announce(guild, updated)

    @app_commands.command(description="排一場讀書會")
    @app_commands.guild_only()
    @app_commands.describe(
        day="YYYY-MM-DD",
        at="HH:MM",
        host="這場的主持人",
        topic="之後可以用 /bookclub topic 改",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def new(
        self,
        interaction: discord.Interaction,
        day: str,
        at: str,
        host: discord.Member,
        topic: str,
    ) -> None:
        try:
            starts_at = schedule.starts_at(date.fromisoformat(day), time.fromisoformat(at))
        except ValueError:
            await interaction.response.send_message(
                f"{BAD_TIME}收到 `{day}` 與 `{at}`。", ephemeral=True
            )
            return

        # Private: the announcement is what tells the channel, so this reply
        # is for the person who scheduled it.
        await interaction.response.defer(ephemeral=True)
        # Asked before inserting, so the reply can say what this changed.
        # A cancelled session still holds the slot, so it is put back on
        # rather than reported as already scheduled.
        found = await store.session(self.db, starts_at)
        if found is not None and found.cancelled_at is not None:
            await store.reopen(self.db, found.id)
            lead = "這場之前取消過，重新排定"
        elif found is not None:
            lead = "這場已經排過，補上缺的部分"
        else:
            lead = "已排定"
        session = await store.ensure(self.db, starts_at)
        await store.set_topic(self.db, session.id, topic)
        # Volunteering spends the turn just as being assigned does.
        await store.assign_host(self.db, session.id, host.id)
        # Re-read, so the event is named after the topic just written.
        session = await store.session(self.db, starts_at) or session
        event_status = await self._add_event(interaction.guild, session)
        announce_status = await self._add_announce(interaction.guild, session)

        await interaction.followup.send(
            f"{lead} {clock.stamp(starts_at)}\n"
            f"主持人：{host.mention}\n"
            f"主題：{session.topic or '未設定'}\n"
            f"活動：{event_status}\n"
            f"公告：{announce_status}",
            ephemeral=True,
            allowed_mentions=SILENT,
        )

    @new.autocomplete("day")
    async def _day_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """The next few weeks, day by day, filtered by what has been typed."""
        today = clock.taipei(clock.now()).date()
        return [
            app_commands.Choice(name=f"{day:%m/%d}（{_weekday(day)}）", value=day.isoformat())
            for day in (today + timedelta(days=n) for n in range(DAY_SPAN))
            if current in day.isoformat()
        ]

    @new.autocomplete("at")
    async def _time_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        # Suggestions, not a closed set: a time typed by hand still works.
        return [app_commands.Choice(name=at, value=at) for at in TIMES if current in at]

    async def _choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """The upcoming sessions, for the `when` option of every command."""
        sessions = await store.upcoming(self.db, self._cutoff())
        return [
            app_commands.Choice(
                name=f"{clock.taipei(s.starts_at):%m/%d %H:%M}　{s.topic or '未設定主題'}"[:100],
                value=s.starts_at.isoformat(),
            )
            for s in sessions
        ]

    def _cutoff(self) -> datetime:
        return schedule.cutoff(clock.now())

    async def _target(self, when: str | None) -> store.Session | None:
        """The session a command acts on: the chosen one, or else the next."""
        if when is None:
            return await store.next_session(self.db, self._cutoff())
        try:
            return await store.session(self.db, datetime.fromisoformat(when))
        except ValueError:
            return None

    async def _resolve(
        self, interaction: discord.Interaction, when: str | None
    ) -> store.Session | None:
        """The session to act on, or None once the refusal has been sent.

        Every command that gets a session here then talks to Discord, which
        outlives the three seconds the token survives, so each defers and
        replies as a follow-up.
        """
        session = await self._target(when)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return None
        if not self._may_manage(interaction, session):
            await interaction.response.send_message(NOT_HOST, ephemeral=True)
            return None
        return session

    async def _sync_event(self, guild: discord.Guild, session: store.Session) -> None:
        """Push the host and topic onto the event; the row must be current."""
        event = await self._event(guild, session)
        if event is None:
            return
        name, description = _event_name(session), _event_description(guild, session)
        if (event.name, event.description or "") == (name, description):
            # The loop syncs every pass, so an unchanged event costs no request.
            return
        try:
            await event.edit(name=name, description=description)
        except discord.HTTPException as error:
            log.warning("event %s not updated: %s", session.event_id, error)

    async def _cancel_event(self, guild: discord.Guild, session: store.Session) -> bool:
        event = await self._event(guild, session)
        if event is None:
            return False
        try:
            # Cancelled rather than deleted: anyone who marked interest gets a
            # notice, and here the session really is off.
            await event.cancel()
        except discord.HTTPException as error:
            log.warning("event %s not cancelled: %s", session.event_id, error)
            return False
        return True

    def _may_manage(self, interaction: discord.Interaction, session: store.Session) -> bool:
        """The host owns their own session; a manager owns all of them."""
        return session.host_user_id == interaction.user.id or permissions.manager_only(interaction)

    @app_commands.command(description="改這場的主持人，輪替順位不動")
    @app_commands.guild_only()
    @app_commands.describe(when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def host(
        self, interaction: discord.Interaction, user: discord.Member, when: str | None = None
    ) -> None:
        session = await self._resolve(interaction, when)
        if session is None:
            return
        await interaction.response.defer(ephemeral=True)
        await store.swap_host(self.db, session.id, user.id)
        await self._sync(interaction.guild, session)
        await self._update(
            interaction,
            session,
            f"{clock.stamp(session.starts_at)} 改由 {user.mention} 主持。"
            "輪替順位不動，所以這場仍算原本被指派那位的輪次。",
        )

    @app_commands.command(description="推掉這輪換下一位，自己的順位保留")
    @app_commands.guild_only()
    @app_commands.describe(when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def skip(self, interaction: discord.Interaction, when: str | None = None) -> None:
        session = await self._resolve(interaction, when)
        if session is None:
            return
        if session.host_user_id is None:
            await interaction.response.send_message(NO_HOST, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        declined = session.host_user_id
        await store.record_skip(self.db, session.id, declined)
        # _assign_host reads the skip records, so the one just written is
        # excluded and a second skip cannot come back to the same person.
        host = await self._assign_host(interaction.guild, session)
        if host is None:
            await store.clear_host(self.db, session.id)
            note = "但沒有其他人可以接手。請管理員用 `/bookclub host` 指派。"
        else:
            note = f"改由 <@{host}> 主持。順位保留，下一場仍優先。"
        await self._sync(interaction.guild, session)
        await self._update(interaction, session, f"<@{declined}> 推掉這場，{note}")

    @app_commands.command(description="設定這場的主題")
    @app_commands.guild_only()
    @app_commands.describe(text="寫進活動名稱與公告", when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def topic(
        self, interaction: discord.Interaction, text: str, when: str | None = None
    ) -> None:
        session = await self._resolve(interaction, when)
        if session is None:
            return
        await interaction.response.defer(ephemeral=True)
        await store.set_topic(self.db, session.id, text)
        await self._sync(interaction.guild, session)
        await self._update(
            interaction, session, f"{clock.stamp(session.starts_at)} 的主題設為「{text}」。"
        )

    @app_commands.command(description="取消下一場，連活動一起")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    @app_commands.describe(when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def cancel(self, interaction: discord.Interaction, when: str | None = None) -> None:
        session = await self._resolve(interaction, when)
        if session is None:
            return
        await interaction.response.defer(ephemeral=True)
        await store.cancel(self.db, session.id, clock.now())
        cancelled = await self._cancel_event(interaction.guild, session)
        await self._sync(interaction.guild, session)
        await self._update(
            interaction,
            session,
            f"已取消 {clock.stamp(session.starts_at)}"
            f"{'，活動也取消了' if cancelled else '（這場本來就沒有建立活動）'}。"
            "這場不算任何人的輪次。",
        )

    @app_commands.command(description="過去的場次與主題")
    @app_commands.guild_only()
    @app_commands.describe(count="要列幾場，預設 10")
    async def history(
        self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 20] = 10
    ) -> None:
        sessions = await store.history(self.db, self._cutoff(), count)
        if not sessions:
            await interaction.response.send_message("還沒有結束的場次。", ephemeral=True)
            return
        lines = []
        for session in sessions:
            host = _mention(session.host_user_id, NO_ASSIGNEE)
            topic = (session.topic or "—")[:40]
            note = "（已取消）" if session.cancelled_at else ""
            lines.append(f"`{clock.taipei(session.starts_at):%Y/%m/%d}`　{host}　{topic}{note}")
        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True, allowed_mentions=SILENT
        )

    @app_commands.command(description="下一場的時間、主持人與主題")
    @app_commands.guild_only()
    async def next(self, interaction: discord.Interaction) -> None:
        session = await self._target(None)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return
        host = _mention(session.host_user_id, NO_ASSIGNEE)
        await interaction.response.send_message(
            f"{clock.stamp(session.starts_at)}（{clock.stamp(session.starts_at, 'R')}）\n"
            f"主持人：{host}\n"
            f"主題：{session.topic or '未設定'}",
            ephemeral=True,
            allowed_mentions=SILENT,
        )

    @tasks.loop(minutes=10)
    async def _tick(self) -> None:
        """Keep the events in step with the database and send what is due."""
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return
        now = clock.now()
        for session in await store.upcoming(self.db, schedule.pending_from(now)):
            # Per session, so one that cannot be handled does not hold up the rest.
            try:
                await self._reconcile(guild, session)
                for kind in schedule.due(session.starts_at, now):
                    await self._send(guild, session, kind, now)
            except Exception:
                log.exception("session %s not handled", session.id)

    @_tick.before_loop
    async def _await_guild(self) -> None:
        # get_guild returns None until the gateway has delivered the guild.
        await self.bot.wait_until_ready()

    @_tick.error
    async def _tick_failed(self, error: BaseException) -> None:
        # The loop does not restart itself, so this is the last word on it.
        log.error("the bookclub loop stopped", exc_info=error)

    async def _reconcile(self, guild: discord.Guild, session: store.Session) -> None:
        """Restore what the row projects: the event, and the sign-up form."""
        if session.event_id is None:
            await self._add_event(guild, session)
        else:
            await self._sync_event(guild, session)
        # Nothing but our own writes changes the form, so a missing one is all
        # there is to restore.
        await self._add_announce(guild, session)

    async def _send(
        self,
        guild: discord.Guild,
        session: store.Session,
        kind: schedule.Reminder,
        now: datetime,
    ) -> None:
        """Claim the reminder before sending it, and release the claim if it fails."""
        if not await store.mark_reminder(self.db, session.id, kind, now):
            return
        try:
            sent = await self._senders[kind](guild, session)
        except Exception:
            # Anything at all: the claim must not outlive a failed send.
            log.exception("%s for session %s failed", kind, session.id)
            sent = False
        if not sent:
            await store.unmark_reminder(self.db, session.id, kind)

    async def _channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await settings.get_id(self.db, Key.BOOKCLUB_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id is not None else None
        if not isinstance(channel, discord.TextChannel):
            log.warning("no bookclub channel set")
            return None
        return channel

    async def _attendees(self, channel: discord.TextChannel, session: store.Session) -> list[int]:
        """Who reacted to the announcement, which is the whole sign-up list."""
        if session.announce_message_id is None:
            return []
        message = await channel.fetch_message(session.announce_message_id)
        for reaction in message.reactions:
            if str(reaction.emoji) == RSVP:
                return [user.id async for user in reaction.users() if not user.bot]
        return []

    async def _remind(self, guild: discord.Guild, session: store.Session) -> bool:
        """A day ahead: nudge whoever signed up."""
        channel = await self._channel(guild)
        if channel is None:
            return False
        await channel.send(
            f"{clock.stamp(session.starts_at)} 讀書會"
            f"（主題：{session.topic or '未設定'}）。\n"
            f"{await self._roll_call(channel, session)}"
            f"{_form_link(channel, session)}",
            allowed_mentions=NOTIFY,
        )
        return True

    async def _starting(self, guild: discord.Guild, session: store.Session) -> bool:
        """An hour ahead: say where, and call the names."""
        channel = await self._channel(guild)
        if channel is None:
            return False
        voice_id = await settings.get_id(self.db, Key.BOOKCLUB_VOICE_CHANNEL)
        where = "" if voice_id is None else f"，在 <#{voice_id}>"
        await channel.send(
            f"讀書會 {clock.stamp(session.starts_at, 'R')} 開始{where}。\n"
            f"主持人：{_mention(session.host_user_id, NO_ASSIGNEE)}\n"
            f"{await self._roll_call(channel, session)}"
            f"{_form_link(channel, session)}",
            allowed_mentions=NOTIFY,
        )
        return True

    async def _followup(self, guild: discord.Guild, session: store.Session) -> bool:
        """Afterwards: name who is up next, and ask for a date."""
        channel = await self._channel(guild)
        if channel is None:
            return False
        candidates = await self._candidates(guild)
        up_next = None if candidates is None else rotation.next_host(candidates, set())
        await channel.send(
            f"{clock.stamp(session.starts_at)} 的讀書會結束了。\n"
            f"下一位輪到 {_mention(up_next, NO_ASSIGNEE)}，"
            "用 `/bookclub new` 排下一場。",
            allowed_mentions=NOTIFY,
        )
        return True

    async def _roll_call(self, channel: discord.TextChannel, session: store.Session) -> str:
        attendees = await self._attendees(channel, session)
        if not attendees:
            return f"還沒有人按 {RSVP} 報名。"
        return "報名：" + " ".join(f"<@{user_id}>" for user_id in attendees)
