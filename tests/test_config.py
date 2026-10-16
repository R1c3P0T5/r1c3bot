from pathlib import Path

import pytest

from ricebot.config import Config, ConfigError

FILLED = {"DISCORD_TOKEN": "token", "GUILD_ID": "1"}


def test_reports_every_missing_variable_in_one_message() -> None:
    with pytest.raises(ConfigError) as error:
        Config.from_env({})

    assert str(error.value) == "missing or empty: DISCORD_TOKEN, GUILD_ID"


def test_reports_blank_and_non_integer_values_together() -> None:
    env = {"DISCORD_TOKEN": "   ", "GUILD_ID": "abc"}

    with pytest.raises(ConfigError) as error:
        Config.from_env(env)

    assert str(error.value) == "missing or empty: DISCORD_TOKEN; not an integer: GUILD_ID='abc'"


def test_parses_the_guild_id_and_defaults_the_database_path() -> None:
    config = Config.from_env(FILLED)

    assert config.guild_id == 1
    assert config.database_path == Path("ricebot.db")
