"""Boot-time configuration, read from the environment exactly once."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

DEFAULT_DATABASE_PATH = Path("ricebot.db")


class ConfigError(Exception):
    """The environment does not describe a usable configuration."""


@dataclass(frozen=True, slots=True)
class Config:
    """Values fixed at boot: the token, the guild, and the channels to act in."""

    token: str
    guild_id: int
    bookclub_channel_id: int
    ctf_announce_channel_id: int
    ctf_category_id: int
    ctf_archive_category_id: int
    database_path: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        """Build a config, reporting every problem with the environment at once."""
        if env is None:
            env = os.environ
        reader = _Reader(env)
        config = cls(
            token=reader.text("DISCORD_TOKEN"),
            guild_id=reader.identifier("GUILD_ID"),
            bookclub_channel_id=reader.identifier("BOOKCLUB_CHANNEL_ID"),
            ctf_announce_channel_id=reader.identifier("CTF_ANNOUNCE_CHANNEL_ID"),
            ctf_category_id=reader.identifier("CTF_CATEGORY_ID"),
            ctf_archive_category_id=reader.identifier("CTF_ARCHIVE_CATEGORY_ID"),
            database_path=Path(env.get("DATABASE_PATH", "").strip() or DEFAULT_DATABASE_PATH),
        )
        reader.raise_for_problems()
        return config


class _Reader:
    """Reads values, collecting problems instead of raising on the first one."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env
        self._missing: list[str] = []
        self._invalid: list[str] = []

    def text(self, name: str) -> str:
        # A variable set to whitespace is a filled-in template, not a value.
        value = self._env.get(name, "").strip()
        if not value:
            self._missing.append(name)
        return value

    def identifier(self, name: str) -> int:
        value = self.text(name)
        if not value:
            return 0
        try:
            return int(value)
        except ValueError:
            self._invalid.append(f"{name}={value!r}")
            return 0

    def raise_for_problems(self) -> None:
        problems = []
        if self._missing:
            problems.append(f"missing or empty: {', '.join(self._missing)}")
        if self._invalid:
            problems.append(f"not an integer: {', '.join(self._invalid)}")
        if problems:
            raise ConfigError("; ".join(problems))
