"""The /bookclub commands."""

import logging
from datetime import date, time

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
NO_ROLE = "還沒設定讀書會身分組，請管理員執行 `/bookclub role`。"
NO_SESSION = "目前沒有排定的場次，用 `/bookclub new` 排一場。"
NO_VOICE = "未建立（請用 `/config` 設定讀書會語音頻道）"
EVENT_NAME = "讀書會"
NOT_HOST = "只有本場主持人或管理員可以這麼做。"
NO_HOST = "這場還沒有指派主持人。"
BAD_TIME = "日期要寫成 YYYY-MM-DD、時間寫成 HH:MM。"


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
                name=EVENT_NAME,
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
        else:
            assigned = await self._assign_host(interaction.guild, session)
        event = await self._add_event(interaction.guild, session)

        await interaction.response.send_message(
            f"已排定 {clock.stamp(starts_at)}\n"
            f"主持人：{f'<@{assigned}>' if assigned else f'未指派（{NO_ROLE}）'}\n"
            f"活動：{'已建立' if event else NO_VOICE}",
            ephemeral=True,
            allowed_mentions=SILENT,
        )

    def _may_manage(self, interaction: discord.Interaction, session: store.Session) -> bool:
        """The host owns their own session; a manager owns all of them."""
        return session.host_user_id == interaction.user.id or permissions.manager_only(interaction)

    @app_commands.command(description="改這場的主持人，輪替順位不動")
    @app_commands.guild_only()
    async def host(self, interaction: discord.Interaction, user: discord.Member) -> None:
        session = await store.next_session(self.db, clock.now() - schedule.DURATION)
        if session is None:
            await interaction.response.send_message(NO_SESSION, ephemeral=True)
            return
        if not self._may_manage(interaction, session):
            await interaction.response.send_message(NOT_HOST, ephemeral=True)
            return

        await store.swap_host(self.db, session.id, user.id)
        await interaction.response.send_message(
            f"{clock.stamp(session.starts_at)} 改由 {user.mention} 主持。"
            "輪替順位不動，所以這場仍算原本被指派那位的輪次。",
            ephemeral=True,
            allowed_mentions=SILENT,
        )

    @app_commands.command(description="推掉這輪換下一位，自己的順位保留")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        session = await store.next_session(self.db, clock.now() - schedule.DURATION)
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
            await interaction.response.send_message(
                f"<@{declined}> 推掉了這場，但沒有其他人可以接手。"
                "請管理員用 `/bookclub host` 指派。",
                ephemeral=True,
                allowed_mentions=SILENT,
            )
            return
        await interaction.response.send_message(
            f"<@{declined}> 推掉這場，改由 <@{host}> 主持。順位保留，下一場仍優先。",
            ephemeral=True,
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
