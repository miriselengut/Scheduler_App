from __future__ import annotations

from constants import PREFERENCE_ALSO_WORKS, PREFERENCE_BEST, SLOT_BY_KEY
from solver import ClientInput, count_segments, solve_schedule


def client(client_id: int, name: str, availability: dict[str, str], sessions: int = 1):
    return ClientInput(client_id, name, availability, sessions)


def test_one_client_uses_best_time() -> None:
    result = solve_schedule(
        clients=[
            client(
                1,
                "Eli",
                {"SUN_1400": PREFERENCE_BEST, "MON_1400": PREFERENCE_ALSO_WORKS},
            )
        ],
        current_schedule={},
    )
    assert result.feasible
    assert result.schedule[1] == ["SUN_1400"]


def test_multiple_sessions_are_on_different_days() -> None:
    result = solve_schedule(
        clients=[
            client(
                1,
                "Eli",
                {
                    "SUN_1400": PREFERENCE_BEST,
                    "SUN_1430": PREFERENCE_BEST,
                    "MON_1400": PREFERENCE_BEST,
                },
                sessions=2,
            )
        ],
        current_schedule={},
    )
    assert result.feasible
    days = {SLOT_BY_KEY[key].day for key in result.schedule[1]}
    assert len(result.schedule[1]) == 2
    assert len(days) == 2


def test_two_clients_cannot_share_one_slot() -> None:
    result = solve_schedule(
        clients=[
            client(1, "A", {"SUN_1400": PREFERENCE_BEST}),
            client(2, "B", {"SUN_1400": PREFERENCE_BEST}),
        ],
        current_schedule={},
    )
    assert result.feasible is False


def test_locked_appointment_does_not_move() -> None:
    result = solve_schedule(
        clients=[
            client(
                1,
                "A",
                {"SUN_1400": PREFERENCE_ALSO_WORKS, "MON_1400": PREFERENCE_BEST},
            )
        ],
        current_schedule={
            1: [{"slot_key": "SUN_1400", "locked": 1}]
        },
    )
    assert result.feasible
    assert result.schedule[1] == ["SUN_1400"]


def test_edited_clients_own_lock_can_move() -> None:
    result = solve_schedule(
        clients=[client(1, "A", {"MON_1400": PREFERENCE_BEST})],
        current_schedule={1: [{"slot_key": "SUN_1400", "locked": 1}]},
        edited_client_ids={1},
    )
    assert result.feasible
    assert result.schedule[1] == ["MON_1400"]


def test_no_move_is_preferred_over_protecting_free_evening() -> None:
    # Current appointment is on preferred Wednesday evening. Moving it to
    # Tuesday would protect Wednesday, but normal scheduling must avoid the move.
    result = solve_schedule(
        clients=[
            client(
                1,
                "A",
                {"WED_2000": PREFERENCE_BEST, "TUE_2000": PREFERENCE_BEST},
            )
        ],
        current_schedule={1: [{"slot_key": "WED_2000", "locked": 0}]},
        preferred_evenings=("Wednesday", "Thursday"),
    )
    assert result.feasible
    assert result.schedule[1] == ["WED_2000"]
    assert result.moved_appointment_count == 0


def test_clustering_avoids_middle_gap_when_higher_priorities_tie() -> None:
    result = solve_schedule(
        clients=[
            client(1, "A", {"SUN_1400": PREFERENCE_BEST}),
            client(
                2,
                "B",
                {"SUN_1430": PREFERENCE_BEST, "SUN_1500": PREFERENCE_BEST},
            ),
        ],
        current_schedule={},
    )
    assert result.feasible
    assert result.schedule[2] == ["SUN_1430"]
    assert count_segments(result.schedule) == 1


def test_preferred_evenings_are_protected_after_move_priority() -> None:
    result = solve_schedule(
        clients=[
            client(
                1,
                "A",
                {"WED_2000": PREFERENCE_BEST, "MON_2000": PREFERENCE_BEST},
            )
        ],
        current_schedule={},
        preferred_evenings=("Wednesday", "Thursday"),
    )
    assert result.feasible
    assert result.schedule[1] == ["MON_2000"]
    assert result.preferred_evenings_free == 2


def test_best_time_wins_after_two_free_evenings_are_preserved() -> None:
    # There are already more than two free evenings either way. The scheduler
    # should not force an afternoon Also works time merely to free one extra evening.
    result = solve_schedule(
        clients=[
            client(
                1,
                "A",
                {"MON_2000": PREFERENCE_BEST, "MON_1400": PREFERENCE_ALSO_WORKS},
            )
        ],
        current_schedule={},
        preferred_evenings=("Wednesday", "Thursday"),
    )
    assert result.feasible
    assert result.schedule[1] == ["MON_2000"]
    assert result.free_evenings == 4
