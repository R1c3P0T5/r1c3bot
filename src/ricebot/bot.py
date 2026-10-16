"""Gateway client: owns the connection, the command tree, and the cogs."""

import logging

import discord
from discord.ext import commands

from ricebot.config import Config

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

    @property
    def guild(self) -> discord.Object:
        return discord.Object(id=self.config.guild_id)

    async def setup_hook(self) -> None:
        # Runs once, after login and before the first connect. on_ready fires
        # again on every reconnect, so one-time setup does not belong there.
        await self.tree.sync(guild=self.guild)

    async def on_ready(self) -> None:
        log.info("logged in as %s (id %s)", self.user, self.user and self.user.id)


def run(config: Config) -> None:
    """Connect and block until the client stops."""
    # setup_logging configures the root logger; log_handler=None stops
    # Client.run from installing a second one.
    discord.utils.setup_logging()
    RiceBot(config).run(config.token, log_handler=None)
