"""The /config panel: one channel picker per setting, for guild managers."""

import logging

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from ricebot.store import settings as store
from ricebot.store.settings import Key

log = logging.getLogger(__name__)

_TEXT = [discord.ChannelType.text]
_VOICE = [discord.ChannelType.voice]
_CATEGORY = [discord.ChannelType.category]

# A select occupies a whole action row and a message holds five, so this list
# is now full. A sixth setting means splitting /config into subcommands, one
# panel per group, rather than squeezing it in.
_FIELDS: list[tuple[str, Key, list[discord.ChannelType]]] = [
    ("讀書會公告頻道", Key.BOOKCLUB_CHANNEL, _TEXT),
    ("讀書會語音頻道", Key.BOOKCLUB_VOICE_CHANNEL, _VOICE),
    ("CTF 公告頻道", Key.CTF_ANNOUNCE_CHANNEL, _TEXT),
    ("CTF 討論頻道分類", Key.CTF_CATEGORY, _CATEGORY),
    ("CTF 封存分類", Key.CTF_ARCHIVE_CATEGORY, _CATEGORY),
]


async def _summary(db: aiosqlite.Connection) -> str:
    """Render the current values, one line per setting."""
    lines = []
    for label, key, _ in _FIELDS:
        channel_id = await store.get_id(db, key)
        # <#id> is resolved by the client, so this needs no channel cache and
        # does not depend on the bot being able to see the channel.
        value = f"<#{channel_id}>" if channel_id is not None else "未設定"
        lines.append(f"**{label}**：{value}")
    # Discord strips trailing whitespace, so a zero-width space is what holds
    # the blank line that separates the list from the selects below it.
    return "## 目前設定\n\n" + "\n".join(lines) + "\n\u200b"


class _Picker(discord.ui.ChannelSelect):
    def __init__(
        self,
        db: aiosqlite.Connection,
        label: str,
        key: Key,
        channel_types: list[discord.ChannelType],
    ) -> None:
        # The placeholder is the label only. It is hidden once the select holds
        # a choice, so it cannot carry the current value.
        super().__init__(
            channel_types=channel_types,
            placeholder=label,
            min_values=1,
            max_values=1,
        )
        self._db = db
        self._key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        await store.put_id(self._db, self._key, channel.id)
        log.info("%s set %s to %s", interaction.user, self._key.value, channel.id)
        await interaction.response.edit_message(content=await _summary(self._db), view=self.view)


class ConfigView(discord.ui.View):
    """The panel itself, ephemeral and short-lived."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        # No custom_id and no persistence: the panel lives on an ephemeral
        # interaction token, so a restart or a timeout means running /config
        # again. Opt-in flows that must survive a restart use reactions.
        super().__init__(timeout=300)
        for label, key, channel_types in _FIELDS:
            self.add_item(_Picker(db, label, key, channel_types))


class SettingsCog(commands.Cog):
    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db

    @app_commands.command(name="config", description="設定 bot 使用的頻道")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def config(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            await _summary(self.db),
            view=ConfigView(self.db),
            ephemeral=True,
        )
