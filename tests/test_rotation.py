from ricebot.bookclub.rotation import Host, next_host

A, B, C = 10, 20, 30


def queue(*rows: tuple[int, int, bool]) -> list[Host]:
    return [Host(user_id=u, position=p, active=a) for u, p, a in rows]


def test_an_empty_queue_has_nobody_to_assign() -> None:
    assert next_host([], 0) is None


def test_an_all_inactive_queue_has_nobody_to_assign() -> None:
    assert next_host(queue((A, 0, False), (B, 1, False)), 0) is None


def test_the_cursor_advances_past_the_assigned_host() -> None:
    assert next_host(queue((A, 0, True), (B, 1, True), (C, 2, True)), 0) == (A, 1)


def test_the_rotation_wraps_to_the_front() -> None:
    assert next_host(queue((A, 0, True), (B, 1, True), (C, 2, True)), 3) == (A, 1)


def test_a_single_host_keeps_being_assigned() -> None:
    # The cursor is already past the only position, so this must wrap rather
    # than run out.
    assert next_host(queue((A, 5, True)), 6) == (A, 6)


def test_an_inactive_host_is_skipped() -> None:
    assert next_host(queue((A, 0, False), (B, 1, True), (C, 2, True)), 0) == (B, 2)


def test_a_gap_left_by_a_removed_host_is_stepped_over() -> None:
    assert next_host(queue((A, 0, True), (C, 7, True)), 1) == (C, 8)


def test_the_queue_order_does_not_depend_on_the_caller() -> None:
    assert next_host(queue((C, 2, True), (A, 0, True), (B, 1, True)), 0) == (A, 1)
