from constants import PREFERENCE_OPTIMAL, PREFERENCE_SECONDARY
from solver import (
    ClientInput,
    count_segments,
    evaluate_client_change,
    evaluate_new_client,
)


def assignment(slot_key: str, name: str, locked: bool = False) -> dict:
    return {"slot_key": slot_key, "name": name, "locked": locked}


def current(*items: tuple[int, dict]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for client_id, item in items:
        result.setdefault(client_id, []).append(item)
    return result


def test_direct_optimal_is_excellent():
    clients = [
        ClientInput(1, "Existing", {"SUN_1400": PREFERENCE_OPTIMAL}),
        ClientInput(2, "New", {"SUN_1430": PREFERENCE_OPTIMAL}),
    ]
    approved = current((1, assignment("SUN_1400", "Existing")))

    result = evaluate_new_client(
        clients=clients,
        new_client_id=2,
        current_schedule=approved,
    )

    assert result.feasible
    assert result.category == "Works excellent"
    assert result.schedule[2] == ["SUN_1430"]
    assert result.moved_client_ids == []


def test_secondary_without_move_works_well():
    clients = [
        ClientInput(1, "Existing", {"SUN_1400": PREFERENCE_OPTIMAL}),
        ClientInput(2, "New", {"SUN_1430": PREFERENCE_SECONDARY}),
    ]
    approved = current((1, assignment("SUN_1400", "Existing")))

    result = evaluate_new_client(
        clients=clients,
        new_client_id=2,
        current_schedule=approved,
    )

    assert result.feasible
    assert result.category == "Works well"
    assert result.schedule[2] == ["SUN_1430"]


def test_rearranges_one_other_client_when_needed():
    clients = [
        ClientInput(
            1,
            "Existing",
            {
                "SUN_1400": PREFERENCE_OPTIMAL,
                "SUN_1430": PREFERENCE_SECONDARY,
            },
        ),
        ClientInput(2, "New", {"SUN_1400": PREFERENCE_OPTIMAL}),
    ]
    approved = current((1, assignment("SUN_1400", "Existing")))

    result = evaluate_new_client(
        clients=clients,
        new_client_id=2,
        current_schedule=approved,
    )

    assert result.feasible
    assert result.category == "Works with rearranging"
    assert result.schedule[2] == ["SUN_1400"]
    assert result.schedule[1] == ["SUN_1430"]
    assert result.moved_client_ids == [1]


def test_locked_client_can_make_new_client_infeasible():
    clients = [
        ClientInput(1, "Existing", {"SUN_1400": PREFERENCE_OPTIMAL}),
        ClientInput(2, "New", {"SUN_1400": PREFERENCE_OPTIMAL}),
    ]
    approved = current((1, assignment("SUN_1400", "Existing", locked=True)))

    result = evaluate_new_client(
        clients=clients,
        new_client_id=2,
        current_schedule=approved,
    )

    assert not result.feasible
    assert result.category == "Cannot fit"


def test_clustering_counts_one_segment_for_consecutive_appointments():
    consecutive = {1: ["SUN_1400"], 2: ["SUN_1430"], 3: ["SUN_1500"]}
    separated = {1: ["SUN_1400"], 2: ["SUN_1500"], 3: ["SUN_1600"]}

    assert count_segments(consecutive) == 1
    assert count_segments(separated) == 3


def test_multiple_sessions_are_scheduled_on_different_days():
    clients = [
        ClientInput(
            1,
            "Twice Weekly",
            {
                "SUN_1400": PREFERENCE_OPTIMAL,
                "SUN_1430": PREFERENCE_OPTIMAL,
                "MON_1400": PREFERENCE_OPTIMAL,
            },
            sessions_per_week=2,
        )
    ]

    result = evaluate_new_client(
        clients=clients,
        new_client_id=1,
        current_schedule={},
    )

    assert result.feasible
    assert len(result.schedule[1]) == 2
    assert {slot.split("_")[0] for slot in result.schedule[1]} == {"SUN", "MON"}


def test_sessions_cannot_exceed_available_days():
    clients = [
        ClientInput(
            1,
            "Twice Weekly",
            {
                "SUN_1400": PREFERENCE_OPTIMAL,
                "SUN_1430": PREFERENCE_OPTIMAL,
            },
            sessions_per_week=2,
        )
    ]

    result = evaluate_new_client(
        clients=clients,
        new_client_id=1,
        current_schedule={},
    )

    assert not result.feasible


def test_edit_can_move_only_the_edited_client():
    clients = [
        ClientInput(1, "Edited", {"MON_1400": PREFERENCE_OPTIMAL}),
        ClientInput(2, "Other", {"SUN_1430": PREFERENCE_OPTIMAL}),
    ]
    approved = current(
        (1, assignment("SUN_1400", "Edited")),
        (2, assignment("SUN_1430", "Other")),
    )

    result = evaluate_client_change(
        clients=clients,
        target_client_id=1,
        current_schedule=approved,
        change_type="edit",
    )

    assert result.feasible
    assert result.schedule[1] == ["MON_1400"]
    assert result.schedule[2] == ["SUN_1430"]
    assert result.moved_client_ids == []

def test_unrelated_unscheduled_client_does_not_block_new_client():
    clients = [
        ClientInput(
            1,
            "Scheduled",
            {"SUN_1400": PREFERENCE_OPTIMAL},
        ),
        ClientInput(
            2,
            "Previously Unscheduled",
            {"SUN_1400": PREFERENCE_OPTIMAL},
        ),
        ClientInput(
            3,
            "New",
            {"SUN_1430": PREFERENCE_OPTIMAL},
        ),
    ]
    approved = current((1, assignment("SUN_1400", "Scheduled", locked=True)))

    result = evaluate_new_client(
        clients=clients,
        new_client_id=3,
        current_schedule=approved,
    )

    assert result.feasible
    assert result.schedule[3] == ["SUN_1430"]
    assert 2 not in result.schedule

