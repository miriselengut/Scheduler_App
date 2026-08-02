from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ortools.sat.python import cp_model

from constants import (
    AFTERNOON_TIMES,
    DAYS,
    EVENING_TIMES,
    PREFERENCE_OPTIMAL,
    PREFERENCE_SECONDARY,
    SLOT_BY_KEY,
    SLOT_KEY_TO_LABEL,
    SLOTS,
)


@dataclass(frozen=True)
class ClientInput:
    id: int
    name: str
    availability: dict[str, str]


@dataclass
class PlacementResult:
    feasible: bool
    category: str
    message: str
    schedule: dict[int, str] = field(default_factory=dict)
    preferences: dict[int, str] = field(default_factory=dict)
    moved_client_ids: list[int] = field(default_factory=list)
    free_evenings: int = 5
    used_segments: int = 0


MOVE_PENALTY = 100_000
EVENING_USE_PENALTY = 10_000
SECONDARY_PENALTY = 1_000
SEGMENT_PENALTY = 50
USED_BLOCK_PENALTY = 10


def count_used_evenings(schedule: dict[int, str]) -> int:
    return len(
        {
            SLOT_BY_KEY[slot_key].day
            for slot_key in schedule.values()
            if SLOT_BY_KEY[slot_key].block == "evening"
        }
    )


def count_free_evenings(schedule: dict[int, str]) -> int:
    return len(DAYS) - count_used_evenings(schedule)


def count_segments(schedule: dict[int, str]) -> int:
    occupied = set(schedule.values())
    segments = 0
    for day in DAYS:
        for block in ("afternoon", "evening"):
            block_slots = sorted(
                [slot for slot in SLOTS if slot.day == day and slot.block == block],
                key=lambda slot: slot.block_index,
            )
            previous_occupied = False
            for slot in block_slots:
                current_occupied = slot.key in occupied
                if current_occupied and not previous_occupied:
                    segments += 1
                previous_occupied = current_occupied
    return segments


def count_used_blocks(schedule: dict[int, str]) -> int:
    return len(
        {
            (SLOT_BY_KEY[slot_key].day, SLOT_BY_KEY[slot_key].block)
            for slot_key in schedule.values()
        }
    )


def _direct_placement(
    *,
    new_client: ClientInput,
    current_schedule: dict[int, dict],
    protect_two_evenings: bool,
) -> PlacementResult | None:
    occupied = {assignment["slot_key"] for assignment in current_schedule.values()}
    base_schedule = {
        client_id: assignment["slot_key"]
        for client_id, assignment in current_schedule.items()
    }

    candidates: list[tuple[tuple[int, int, int], str, dict[int, str]]] = []
    for slot_key, preference in new_client.availability.items():
        if slot_key in occupied:
            continue
        proposed = dict(base_schedule)
        proposed[new_client.id] = slot_key
        free_evenings = count_free_evenings(proposed)
        if protect_two_evenings and free_evenings < 2:
            continue

        score = (
            0 if preference == PREFERENCE_OPTIMAL else 1,
            count_segments(proposed),
            count_used_blocks(proposed),
        )
        candidates.append((score, slot_key, proposed))

    if not candidates:
        return None

    _, chosen_slot, schedule = min(candidates, key=lambda item: item[0])
    chosen_preference = new_client.availability[chosen_slot]
    free_evenings = count_free_evenings(schedule)

    if free_evenings < 2:
        category = "Works, but uses a protected evening"
    elif chosen_preference == PREFERENCE_OPTIMAL:
        category = "Works excellent"
    else:
        category = "Works well"

    message = (
        f"{new_client.name} can be added at {SLOT_KEY_TO_LABEL[chosen_slot]}. "
        f"This is a {chosen_preference} time. No existing appointments need to move. "
        f"{free_evenings} evening(s) remain completely free."
    )

    preferences = {
        client_id: (
            new_client.availability[slot_key]
            if client_id == new_client.id
            else "current"
        )
        for client_id, slot_key in schedule.items()
    }

    return PlacementResult(
        feasible=True,
        category=category,
        message=message,
        schedule=schedule,
        preferences=preferences,
        moved_client_ids=[],
        free_evenings=free_evenings,
        used_segments=count_segments(schedule),
    )


def _solve_with_rearrangement(
    *,
    clients: list[ClientInput],
    current_schedule: dict[int, dict],
    protect_two_evenings: bool,
    max_seconds: float = 5.0,
) -> PlacementResult | None:
    model = cp_model.CpModel()
    x: dict[tuple[int, str], cp_model.IntVar] = {}

    for client in clients:
        for slot_key in client.availability:
            x[(client.id, slot_key)] = model.NewBoolVar(f"c{client.id}_{slot_key}")

    for client in clients:
        client_vars = [x[(client.id, slot_key)] for slot_key in client.availability]
        if not client_vars:
            return None
        model.Add(sum(client_vars) == 1)

    occupancy: dict[str, cp_model.IntVar] = {}
    for slot in SLOTS:
        slot_vars = [
            x[(client.id, slot.key)]
            for client in clients
            if (client.id, slot.key) in x
        ]
        occupancy[slot.key] = model.NewBoolVar(f"occupied_{slot.key}")
        if slot_vars:
            model.Add(sum(slot_vars) == occupancy[slot.key])
        else:
            model.Add(occupancy[slot.key] == 0)

    for client_id, assignment in current_schedule.items():
        if assignment.get("locked"):
            current_slot = assignment["slot_key"]
            variable = x.get((client_id, current_slot))
            if variable is None:
                return None
            model.Add(variable == 1)

    evening_used: dict[str, cp_model.IntVar] = {}
    block_used: list[cp_model.IntVar] = []
    segment_starts: list[cp_model.IntVar] = []

    for day in DAYS:
        evening_slots = [
            occupancy[slot.key]
            for slot in SLOTS
            if slot.day == day and slot.block == "evening"
        ]
        evening_used[day] = model.NewBoolVar(f"evening_used_{day}")
        model.AddMaxEquality(evening_used[day], evening_slots)

        for block in ("afternoon", "evening"):
            ordered_slots = sorted(
                [slot for slot in SLOTS if slot.day == day and slot.block == block],
                key=lambda slot: slot.block_index,
            )
            used = model.NewBoolVar(f"block_used_{day}_{block}")
            model.AddMaxEquality(used, [occupancy[slot.key] for slot in ordered_slots])
            block_used.append(used)

            for index, slot in enumerate(ordered_slots):
                start = model.NewBoolVar(f"segment_start_{slot.key}")
                current = occupancy[slot.key]
                if index == 0:
                    model.Add(start == current)
                else:
                    previous = occupancy[ordered_slots[index - 1].key]
                    model.Add(start >= current - previous)
                    model.Add(start <= current)
                    model.Add(start <= 1 - previous)
                segment_starts.append(start)

    if protect_two_evenings:
        model.Add(sum(evening_used.values()) <= 3)

    move_terms = []
    for client_id, assignment in current_schedule.items():
        current_slot = assignment["slot_key"]
        current_variable = x.get((client_id, current_slot))
        if current_variable is None:
            move_terms.append(1)
        else:
            move_terms.append(1 - current_variable)

    secondary_terms = [
        variable
        for client in clients
        for slot_key, preference in client.availability.items()
        if preference == PREFERENCE_SECONDARY
        for variable in [x[(client.id, slot_key)]]
    ]

    objective = (
        MOVE_PENALTY * sum(move_terms)
        + SECONDARY_PENALTY * sum(secondary_terms)
        + SEGMENT_PENALTY * sum(segment_starts)
        + USED_BLOCK_PENALTY * sum(block_used)
    )
    if not protect_two_evenings:
        objective += EVENING_USE_PENALTY * sum(evening_used.values())

    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    schedule: dict[int, str] = {}
    preferences: dict[int, str] = {}
    client_by_id = {client.id: client for client in clients}
    for client in clients:
        for slot_key, preference in client.availability.items():
            if solver.Value(x[(client.id, slot_key)]) == 1:
                schedule[client.id] = slot_key
                preferences[client.id] = preference
                break

    moved_client_ids = [
        client_id
        for client_id, assignment in current_schedule.items()
        if schedule.get(client_id) != assignment["slot_key"]
    ]
    free_evenings = count_free_evenings(schedule)

    if free_evenings < 2:
        category = "Works, but uses a protected evening"
    elif moved_client_ids:
        category = "Works with rearranging"
    else:
        category = "Works well"

    if moved_client_ids:
        moved_names = ", ".join(client_by_id[client_id].name for client_id in moved_client_ids)
        movement_sentence = f"Existing appointment(s) moved: {moved_names}."
    else:
        movement_sentence = "No existing appointments need to move."

    message = (
        f"A valid weekly schedule was found. {movement_sentence} "
        f"{free_evenings} evening(s) remain completely free."
    )

    return PlacementResult(
        feasible=True,
        category=category,
        message=message,
        schedule=schedule,
        preferences=preferences,
        moved_client_ids=moved_client_ids,
        free_evenings=free_evenings,
        used_segments=count_segments(schedule),
    )


def evaluate_new_client(
    *,
    clients: list[ClientInput],
    new_client_id: int,
    current_schedule: dict[int, dict],
) -> PlacementResult:
    client_by_id = {client.id: client for client in clients}
    new_client = client_by_id[new_client_id]

    other_client_ids = {client.id for client in clients if client.id != new_client_id}
    all_other_clients_currently_scheduled = other_client_ids.issubset(current_schedule)

    # 1. Direct insertion while preserving at least two free evenings.
    if all_other_clients_currently_scheduled:
        result = _direct_placement(
            new_client=new_client,
            current_schedule=current_schedule,
            protect_two_evenings=True,
        )
        if result:
            result.preferences = {
                client_id: client_by_id[client_id].availability[slot_key]
                for client_id, slot_key in result.schedule.items()
            }
            return result

    # 2. Rearrangement while preserving at least two free evenings.
    result = _solve_with_rearrangement(
        clients=clients,
        current_schedule=current_schedule,
        protect_two_evenings=True,
    )
    if result:
        return result

    # 3. Direct insertion that requires using another evening.
    if all_other_clients_currently_scheduled:
        result = _direct_placement(
            new_client=new_client,
            current_schedule=current_schedule,
            protect_two_evenings=False,
        )
        if result:
            result.preferences = {
                client_id: client_by_id[client_id].availability[slot_key]
                for client_id, slot_key in result.schedule.items()
            }
            return result

    # 4. Rearrangement without the protected-evening restriction.
    result = _solve_with_rearrangement(
        clients=clients,
        current_schedule=current_schedule,
        protect_two_evenings=False,
    )
    if result:
        return result

    return PlacementResult(
        feasible=False,
        category="Cannot fit",
        message=(
            f"{new_client.name} cannot be placed in any optimal or secondary time. "
            "No valid rearrangement was found using the current client availability and locked appointments."
        ),
        schedule={
            client_id: assignment["slot_key"]
            for client_id, assignment in current_schedule.items()
        },
        preferences={},
        moved_client_ids=[],
        free_evenings=count_free_evenings(
            {
                client_id: assignment["slot_key"]
                for client_id, assignment in current_schedule.items()
            }
        ),
    )