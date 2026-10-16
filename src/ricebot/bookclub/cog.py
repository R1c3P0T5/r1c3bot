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

    @app_commands.command(description="排一場讀書會")
    @app_commands.guild_only()
    @app_commands.describe(day="YYYY-MM-DD", at="HH:MM，預設 20:00")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(permissions.manager_only)
    async def new(self, interaction: discord.Interaction, day: str, at: str = "20:00") -> None:
        try:
            starts_at = schedule.starts_at(date.fromisoformat(day), time.fromisoformat(at))
        except ValueError:
            await interaction.response.send_message(
                f"{BAD_TIME}收到 `{day}` 與 `{at}`。", ephemeral=True
            )
            return

        session = await store.ensure(self.db, starts_at)
        candidates = await self._candidates(interaction.guild)
        if candidates is None:
            await interaction.response.send_message(
                f"已排定 {clock.stamp(starts_at)}，但{NO_ROLE}", ephemeral=True
            )
            return

        host = rotation.next_host(candidates, await store.skipped(self.db, session.id))
        if host is None:
            await interaction.response.send_message(
                f"已排定 {clock.stamp(starts_at)}，但身分組裡沒有可指派的人。", ephemeral=True
            )
            return

        await store.assign_host(self.db, session.id, host)
        await interaction.response.send_message(
            f"已排定 {clock.stamp(starts_at)}，主持人 <@{host}>。公告會在七天前自動發出。",
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
