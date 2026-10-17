"""The audit log: who ran which command, and what it changed."""

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from ricebot import clock
from ricebot.store import audit as store

# Reads change nothing, so they are not part of the record.
READS = frozenset({"bookclub next", "bookclub history"})


def _options(namespace: app_commands.Namespace) -> str:
    """The options as given, as mentions where the client renders them."""
    return " ".join(
        f"{name}={getattr(value, 'mention', value)}" for name, value in vars(namespace).items()
    )


async def record(
    db: aiosqlite.Connection, interaction: discord.Interaction, command: str, options: str
) -> None:
    """Record what an interaction changed, under the name of the command it came from."""
    await store.record(
        db,
        store.Entry(
            at=clock.now(),
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            command=command,
            options=options,
        ),
    )


class AuditCog(commands.Cog):
    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        # Completion, not invocation: a command that was refused or failed
        # changed nothing, and permissions.on_error logs those.
        if command.qualified_name in READS:
            return
        await record(self.db, interaction, command.qualified_name, _options(interaction.namespace))
