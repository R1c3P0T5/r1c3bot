"""The /bookclub commands."""

import logging
from datetime import date, datetime, time, timedelta

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from ricebot import clock, permissions
from ricebot.bookclub import rotation, schedule
from ricebot.store import bookclub as store
from ricebot.store import settings
from ricebot.store.settings import Key

log = logging.getLogger(__name__)

SILENT = discord.AllowedMentions.none()
# A change of host is worth a notification; a topic or a cancellation is not.
NOTIFY = discord.AllowedMentions(users=True)
NO_ROLE = "還沒設定讀書會身分組，請管理員執行 `/bookclub role`。"
NO_SESSION = "目前沒有排定的場次，用 `/bookclub new` 排一場。"
NO_VOICE = "未建立（請用 `/config` 設定讀書會語音頻道）"
EVENT_NAME = "讀書會"
NOT_HOST = "只有本場主持人或管理員可以這麼做。"
NO_HOST = "這場還沒有指派主持人。"
# Offsets from the last session, the usual fortnight first.
DAY_OFFSETS = (14, 7, 21, 28, 35, 42)
# Half hours from morning to the usual start. 08:00 to 20:00 inclusive is
# exactly 25 entries, which is also Discord's limit for an autocomplete reply.
TIMES = tuple(f"{t // 60:02d}:{t % 60:02d}" for t in range(8 * 60, 20 * 60 + 1, 30))
BAD_TIME = "日期要寫成 YYYY-MM-DD、時間寫成 HH:MM。"


_WEEKDAYS = "一二三四五六日"


def _weekday(day: date) -> str:
    return f"週{_WEEKDAYS[day.weekday()]}"


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
    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db

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

    async def _add_event(self, guild: discord.Guild, session: store.Session) -> int | None:
        """Put the session on the guild calendar, bound to the voice channel."""
        if session.event_id is not None:
            return session.event_id
        channel_id = await settings.get_id(self.db, Key.BOOKCLUB_VOICE_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            return None
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
            return None
        await store.set_event(self.db, session.id, event.id)
        return event.id

    @app_commands.command(description="排一場讀書會")
    @app_commands.guild_only()
    @app_commands.describe(day="YYYY-MM-DD", at="HH:MM，預設 20:00", host="不給就照輪替指派")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def new(
        self,
        interaction: discord.Interaction,
        day: str,
        at: str = "20:00",
        host: discord.Member | None = None,
    ) -> None:
        try:
            starts_at = schedule.starts_at(date.fromisoformat(day), time.fromisoformat(at))
        except ValueError:
            await interaction.response.send_message(
                f"{BAD_TIME}收到 `{day}` 與 `{at}`。", ephemeral=True
            )
            return

        session = await store.ensure(self.db, starts_at)
        if host is not None:
            # Volunteering spends the turn just as being assigned does.
            await store.assign_host(self.db, session.id, host.id)
            assigned: int | None = host.id
        elif session.host_user_id is not None:
            # The session already existed, so re-running new must not reshuffle
            # its host: the rotation would pick someone else, having already
            # counted this session's turn.
            assigned = session.host_user_id
        else:
            assigned = await self._assign_host(interaction.guild, session)
        event = await self._add_event(interaction.guild, session)

        await interaction.response.send_message(
            f"已排定 {clock.stamp(starts_at)}\n"
            f"主持人：{f'<@{assigned}>' if assigned else f'未指派（{NO_ROLE}）'}\n"
            f"活動：{'已建立' if event else NO_VOICE}",
            allowed_mentions=NOTIFY,
        )

    @new.autocomplete("day")
    async def _day_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Candidate dates counted from the last session, fortnight first."""
        last = await store.latest(self.db)
        base = clock.taipei(last.starts_at if last else clock.now()).date()
        return [
            app_commands.Choice(
                name=f"{day:%m/%d}（{_weekday(day)}）"
                + ("　上一場 + 2 週" if offset == 14 and last else ""),
                value=day.isoformat(),
            )
            for offset, day in ((n, base + timedelta(days=n)) for n in DAY_OFFSETS)
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
        sessions = await store.upcoming(self.db, clock.now() - schedule.DURATION)
        return [
            app_commands.Choice(
                name=f"{clock.taipei(s.starts_at):%m/%d %H:%M}　{s.topic or '未設定主題'}"[:100],
                value=s.starts_at.isoformat(),
            )
            for s in sessions
        ]

    async def _target(self, when: str | None) -> store.Session | None:
        """The session a command acts on: the chosen one, or else the next."""
        if when is None:
            # A session in progress is still the next one, hence the duration.
            return await store.next_session(self.db, clock.now() - schedule.DURATION)
        try:
            return await store.session(self.db, datetime.fromisoformat(when))
        except ValueError:
            return None

    async def _sync_event(self, guild: discord.Guild, session: store.Session) -> None:
        """Push the session's host and topic onto its event."""
        if session.event_id is None:
            return
        event = guild.get_scheduled_event(session.event_id)
        if event is None:
            return
        try:
            await event.edit(
                name=_event_name(session), description=_event_description(guild, session)
            )
        except discord.HTTPException as error:
            log.warning("event %s not updated: %s", session.event_id, error)

    async def _refresh_event(self, guild: discord.Guild, session: store.Session) -> None:
        """Re-read the session, then sync, so the event shows the new values."""
        updated = await store.session(self.db, session.starts_at)
        if updated is not None:
            await self._sync_event(guild, updated)

    async def _cancel_event(self, guild: discord.Guild, session: store.Session) -> bool:
        if session.event_id is None:
            return False
        event = guild.get_scheduled_event(session.event_id)
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
        session = await self._target(when)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return
        if not self._may_manage(interaction, session):
            await interaction.response.send_message(NOT_HOST, ephemeral=True)
            return

        await store.swap_host(self.db, session.id, user.id)
        await self._refresh_event(interaction.guild, session)
        await interaction.response.send_message(
            f"{clock.stamp(session.starts_at)} 改由 {user.mention} 主持。"
            "輪替順位不動，所以這場仍算原本被指派那位的輪次。",
            allowed_mentions=NOTIFY,
        )

    @app_commands.command(description="推掉這輪換下一位，自己的順位保留")
    @app_commands.guild_only()
    @app_commands.describe(when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def skip(self, interaction: discord.Interaction, when: str | None = None) -> None:
        session = await self._target(when)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return
        if session.host_user_id is None:
            await interaction.response.send_message(NO_HOST, ephemeral=True)
            return
        if not self._may_manage(interaction, session):
            await interaction.response.send_message(NOT_HOST, ephemeral=True)
            return

        declined = session.host_user_id
        await store.record_skip(self.db, session.id, declined)
        # _assign_host reads the skip records, so the one just written is
        # excluded and a second skip cannot come back to the same person.
        host = await self._assign_host(interaction.guild, session)
        if host is None:
            await store.clear_host(self.db, session.id)
            await self._refresh_event(interaction.guild, session)
            await interaction.response.send_message(
                f"<@{declined}> 推掉了這場，但沒有其他人可以接手。"
                "請管理員用 `/bookclub host` 指派。",
                allowed_mentions=NOTIFY,
            )
            return
        await self._refresh_event(interaction.guild, session)
        await interaction.response.send_message(
            f"<@{declined}> 推掉這場，改由 <@{host}> 主持。順位保留，下一場仍優先。",
            allowed_mentions=NOTIFY,
        )

    @app_commands.command(description="設定這場的主題")
    @app_commands.guild_only()
    @app_commands.describe(text="寫進活動名稱與公告", when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def topic(
        self, interaction: discord.Interaction, text: str, when: str | None = None
    ) -> None:
        session = await self._target(when)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return
        if not self._may_manage(interaction, session):
            await interaction.response.send_message(NOT_HOST, ephemeral=True)
            return

        await store.set_topic(self.db, session.id, text)
        await self._refresh_event(interaction.guild, session)
        await interaction.response.send_message(
            f"{clock.stamp(session.starts_at)} 的主題設為「{text}」。",
            allowed_mentions=SILENT,
        )

    @app_commands.command(description="取消下一場，連活動一起")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    @app_commands.describe(when="哪一場，不給就是下一場")
    @app_commands.autocomplete(when=_choices)
    async def cancel(self, interaction: discord.Interaction, when: str | None = None) -> None:
        session = await self._target(when)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return

        await store.cancel(self.db, session.id, clock.now())
        cancelled = await self._cancel_event(interaction.guild, session)
        await interaction.response.send_message(
            f"已取消 {clock.stamp(session.starts_at)}"
            f"{'，活動也取消了' if cancelled else '（沒有活動可取消）'}。"
            "這場不算任何人的輪次。",
            allowed_mentions=SILENT,
        )

    @app_commands.command(description="下一場的時間、主持人與主題")
    @app_commands.guild_only()
    async def next(self, interaction: discord.Interaction) -> None:
        # A session in progress is still the next one, hence the duration.
        session = await store.next_session(self.db, clock.now() - schedule.DURATION)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return
        host = f"<@{session.host_user_id}>" if session.host_user_id else "未指派"
        await interaction.response.send_message(
            f"{clock.stamp(session.starts_at)}（{clock.stamp(session.starts_at, 'R')}）\n"
            f"主持人：{host}\n"
            f"主題：{session.topic or '未設定'}",
            ephemeral=True,
            allowed_mentions=SILENT,
        )
