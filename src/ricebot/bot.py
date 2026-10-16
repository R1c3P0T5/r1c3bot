"""Gateway client: owns the connection, the command tree, and the cogs."""

import logging

import aiosqlite
import discord
from discord.ext import commands

from ricebot.config import Config
from ricebot.settings import SettingsCog
from ricebot.store.db import connect

log = logging.getLogger(__name__)


def _intents() -> discord.Intents:
    # Intents.default() enables every non-privileged intent, which costs cache
    # and gateway traffic for events nothing reads. Start from none instead.
    intents = discord.Intents.none()
    intents.guilds = True
    intents.reactions = True
    return intents


class RiceBot(commands.Bot):
    """The single-guild client for the r1c3p0t5 community."""

    def __init__(self, config: Config) -> None:
        # Prefix commands cannot fire without the message_content intent; the
        # prefix exists only because commands.Bot requires one.
        super().__init__(command_prefix=commands.when_mentioned, intents=_intents())
        self.config = config
        self.db: aiosqlite.Connection | None = None

    @property
    def guild(self) -> discord.Object:
        return discord.Object(id=self.config.guild_id)

    async def setup_hook(self) -> None:
        # Runs once, after login and before the first connect. on_ready fires
        # again on every reconnect, so one-time setup does not belong there.
        self.db = await connect(self.config.database_path)
        await self.add_cog(SettingsCog(self.db))
        # Commands declared in a cog are global, and sync(guild=...) uploads
        # only what is assigned to that guild. Without the copy it would PUT an
        # empty list, which Discord accepts as "replace with nothing" and so
        # clears the guild's commands on every start.
        self.tree.copy_global_to(guild=self.guild)
        await self.tree.sync(guild=self.guild)

    async def close(self) -> None:
        # Close the gateway before the database so no handler is still running.
        await super().close()
        if self.db is not None:
            await self.db.close()

    async def on_ready(self) -> None:
        log.info("logged in as %s (id %s)", self.user, self.user and self.user.id)
        # Logging in says nothing about membership, and being in no guild at all
        # is a silent success: the client connects and idles forever.
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
    # setup_logging configures the root logger; log_handler=None stops
    # Client.run from installing a second one.
    discord.utils.setup_logging()
    RiceBot(config).run(config.token, log_handler=None)
