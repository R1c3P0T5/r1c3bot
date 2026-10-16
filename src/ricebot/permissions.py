"""Authorisation for the command tree."""

import logging

import discord
from discord import app_commands

log = logging.getLogger(__name__)

DENIED = "需要「管理伺服器」權限。"
FAILED = "指令執行失敗，已記錄在 log。"


def manager_only(interaction: discord.Interaction) -> bool:
    """Whether the caller may change settings.

    default_permissions is only a default: a guild can override it per command
    in its integration settings, so the check has to run here as well.
    """
    user = interaction.user
    return isinstance(user, discord.Member) and user.guild_permissions.manage_guild


async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    """Tell the caller why their command did not run.

    An interaction left unanswered shows as "the application did not respond",
    which says neither "you lack permission" nor "it crashed".
    """
    # A refusal is expected behaviour, so it is answered but not logged.
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(DENIED, ephemeral=True)
        return
    name = interaction.command.name if interaction.command else "unknown"
    log.error("/%s failed", name, exc_info=error)
    # An interaction already answered can only be followed up, not replied to.
    if interaction.response.is_done():
        await interaction.followup.send(FAILED, ephemeral=True)
    else:
        await interaction.response.send_message(FAILED, ephemeral=True)
