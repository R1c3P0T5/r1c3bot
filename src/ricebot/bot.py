"""Gateway client: owns the connection, the command tree, and the cogs."""

import logging

import aiosqlite
import discord
from discord.ext import commands

from ricebot.audit import AuditCog
from ricebot.bookclub.cog import BookclubCog
from ricebot.config import Config
from ricebot.settings import SettingsCog
from ricebot.store.db import connect

log = logging.getLogger(__name__)


def _intents() -> discord.Intents:
    # Intents.default() enables every non-privileged intent, most of them unread.
    intents = discord.Intents.none()
    intents.guilds = True
    # Privileged, but a Developer Portal toggle below 100 guilds. The host
    # rotation needs the role's members, which no unprivileged API exposes.
    intents.members = True
    intents.reactions = True
    return intents


class RiceBot(commands.Bot):
    """The single-guild client for the r1c3p0t5 community."""

    def __init__(self, config: Config) -> None:
        # Unreachable without message_content, but commands.Bot requires a prefix.
        super().__init__(command_prefix=commands.when_mentioned, intents=_intents())
        self.config = config
        self.db: aiosqlite.Connection | None = None

    @property
    def guild(self) -> discord.Object:
        return discord.Object(id=self.config.guild_id)

    async def setup_hook(self) -> None:
        # Runs once between login and the first connect; on_ready repeats.
        self.db = await connect(self.config.database_path)
        await self.add_cog(AuditCog(self.db))
        await self.add_cog(SettingsCog(self.db))
        await self.add_cog(BookclubCog(self.db))
        # Cog commands are global; without the copy, sync uploads an empty list.
        self.tree.copy_global_to(guild=self.guild)
        await self.tree.sync(guild=self.guild)

    async def close(self) -> None:
        # Close the gateway before the database so no handler is still running.
        await super().close()
        if self.db is not None:
            await self.db.close()

    async def on_ready(self) -> None:
        log.info("logged in as %s (id %s)", self.user, self.user and self.user.id)
        # Logging in says nothing about membership, and joining nothing is silent.
        guild = self.get_guild(self.config.guild_id)
        if guild is None:
            log.error(
                "not in guild %s. currently in: %s. invite the bot, then restart",
                self.config.guild_id,
                ", ".join(f"{g.name} ({g.id})" for g in self.guilds) or "nothing",
            )
        else:
            log.info("serving %s (%s)", guild.name, guild.id)


def run(config: Config) -> None:
    """Connect and block until the client stops."""
    # log_handler=None stops Client.run installing a second root handler.
    discord.utils.setup_logging()
    try:
        RiceBot(config).run(config.token, log_handler=None)
    except discord.PrivilegedIntentsRequired as error:
        # Otherwise this surfaces as a reconnect loop with no stated cause.
        raise SystemExit(
            "ricebot: a privileged intent is not enabled for this application.\n"
            "Developer Portal -> Bot -> Privileged Gateway Intents -> Server Members Intent\n"
            f"({error})"
        ) from None
