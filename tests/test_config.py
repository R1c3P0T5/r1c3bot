from pathlib import Path

import pytest

from ricebot.config import Config, ConfigError

FILLED = {
    "DISCORD_TOKEN": "token",
    "GUILD_ID": "1",
    "BOOKCLUB_CHANNEL_ID": "2",
    "CTF_ANNOUNCE_CHANNEL_ID": "3",
    "CTF_CATEGORY_ID": "4",
    "CTF_ARCHIVE_CATEGORY_ID": "5",
}


def test_reports_every_missing_variable_in_one_message() -> None:
    with pytest.raises(ConfigError) as error:
        Config.from_env({"DISCORD_TOKEN": "token", "GUILD_ID": "1"})

    assert str(error.value) == (
        "missing or empty: BOOKCLUB_CHANNEL_ID, CTF_ANNOUNCE_CHANNEL_ID, "
        "CTF_CATEGORY_ID, CTF_ARCHIVE_CATEGORY_ID"
    )


def test_reports_blank_and_non_integer_values_together() -> None:
    env = FILLED | {"DISCORD_TOKEN": "   ", "CTF_CATEGORY_ID": "abc"}

    with pytest.raises(ConfigError) as error:
        Config.from_env(env)

    assert str(error.value) == (
        "missing or empty: DISCORD_TOKEN; not an integer: CTF_CATEGORY_ID='abc'"
    )


def test_parses_identifiers_and_defaults_the_database_path() -> None:
    config = Config.from_env(FILLED)

    assert config.guild_id == 1
    assert config.ctf_archive_category_id == 5
    assert config.database_path == Path("ricebot.db")
