from ricebot.store import settings
from ricebot.store.settings import Key


async def test_returns_none_for_a_setting_never_set(store) -> None:
    assert await settings.get(store, Key.CTF_CATEGORY) is None
    assert await settings.get_id(store, Key.CTF_CATEGORY) is None


async def test_a_second_write_replaces_the_first(store) -> None:
    await settings.put_id(store, Key.BOOKCLUB_CHANNEL, 111)
    await settings.put_id(store, Key.BOOKCLUB_CHANNEL, 222)

    assert await settings.get_id(store, Key.BOOKCLUB_CHANNEL) == 222


async def test_an_id_reads_back_as_an_int(store) -> None:
    await settings.put_id(store, Key.CTF_ANNOUNCE_CHANNEL, 1560613263123812392)

    # A snowflake kept as text compares unequal to every Discord id.
    assert await settings.get_id(store, Key.CTF_ANNOUNCE_CHANNEL) == 1560613263123812392


async def test_keys_are_independent(store) -> None:
    await settings.put_id(store, Key.CTF_CATEGORY, 1)
    await settings.put_id(store, Key.CTF_ARCHIVE_CATEGORY, 2)

    assert await settings.get_id(store, Key.CTF_CATEGORY) == 1
    assert await settings.get_id(store, Key.CTF_ARCHIVE_CATEGORY) == 2


async def test_a_number_comes_back_as_a_float(store) -> None:
    await settings.put(store, Key.CTF_WEIGHT_FLOOR, "35.39")

    assert await settings.get_float(store, Key.CTF_WEIGHT_FLOOR) == 35.39


async def test_a_number_never_set_is_none(store) -> None:
    assert await settings.get_float(store, Key.CTF_LOOKAHEAD_DAYS) is None
