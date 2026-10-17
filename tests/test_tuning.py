from ricebot.ctf import tuning


def test_a_value_at_either_end_of_a_range_is_accepted() -> None:
    # Both ends are included, so a strict comparison would refuse what the
    # label invites.
    assert tuning.parse("-1", "1", "0") == tuning.Tuning(-1.0, 1.0, 0.0)
    assert tuning.parse("100", "60", "60") == tuning.Tuning(100.0, 60.0, 60.0)


def test_a_value_just_past_a_range_is_refused() -> None:
    assert tuning.parse("100.1", "60", "60") is None
    assert tuning.parse("100", "0", "60") is None
    assert tuning.parse("100", "60", "61") is None


def test_one_unusable_field_discards_the_other_two() -> None:
    assert tuning.parse("25", "21", "每隔兩天") is None


def test_a_number_that_no_comparison_admits_is_refused() -> None:
    # float() accepts both, and every bounds check against them is False.
    assert tuning.parse("inf", "21", "2") is None
    assert tuning.parse("nan", "21", "2") is None


def test_a_fractional_weight_floor_survives_as_it_was_typed() -> None:
    # Rounding it would quietly change which contests are announced.
    assert tuning.parse("35.39", "21", "2") == tuning.Tuning(35.39, 21.0, 2.0)


def test_a_range_is_printed_from_the_bounds_it_enforces() -> None:
    # "-1.0 到 100.0" in a label reads as a precision the field has not got.
    assert tuning.bounds_text((-1.0, 100.0)) == "-1 到 100"
