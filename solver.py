from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ortools.sat.python import cp_model

from constants import (
    DAYS,
    PREFERENCE_ALSO_WORKS,
    PREFERENCE_BEST,
    SLOT_BY_KEY,
    SLOTS,
)
from project_version import EXPECTED_BUILD


@dataclass(frozen=True)
class ClientInput:
    id: int
    name: str
    availability: dict[str, str]
    sessions_per_week: int = 1


@dataclass
class ScheduleResult:
    feasible: bool
    schedule: dict[int, list[str]] = field(default_factory=dict)
    preferences: dict[tuple[int, str], str] = field(default_factory=dict)
    moved_client_ids: list[int] = field(default_factory=list)
    moved_appointment_count: int = 0
    unchanged_client_moves: int = 0
    edited_client_moves: int = 0
    free_evenings: int = 5
    preferred_evenings_free: int = 2
    used_segments: int = 0
    used_blocks: int = 0
    secondary_count: int = 0
    build_version: str = EXPECTED_BUILD


def _slot_values(schedule: dict[int, list[str]]) -> list[str]:
    return [slot_key for slots in schedule.values() for slot_key in slots]


def count_used_evenings(schedule: dict[int, list[str]]) -> int:
    return len(
        {
            SLOT_BY_KEY[slot_key].day
            for slot_key in _slot_values(schedule)
            if SLOT_BY_KEY[slot_key].block == "evening"
        }
    )


def count_free_evenings(schedule: dict[int, list[str]]) -> int:
    return len(DAYS) - count_used_evenings(schedule)


def count_preferred_evenings_free(
    schedule: dict[int, list[str]], preferred_evenings: Iterable[str]
) -> int:
    used = {
        SLOT_BY_KEY[slot_key].day
        for slot_key in _slot_values(schedule)
        if SLOT_BY_KEY[slot_key].block == "evening"
    }
    return sum(day not in used for day in preferred_evenings)


def count_segments(schedule: dict[int, list[str]]) -> int:
    occupied = set(_slot_values(schedule))
    segments = 0
    for day in DAYS:
        for block in ("afternoon", "evening"):
            ordered = sorted(
                [slot for slot in SLOTS if slot.day == day and slot.block == block],
                key=lambda slot: slot.block_index,
            )
            previous_occupied = False
            for slot in ordered:
                current_occupied = slot.key in occupied
                if current_occupied and not previous_occupied:
                    segments += 1
                previous_occupied = current_occupied
    return segments


def count_used_blocks(schedule: dict[int, list[str]]) -> int:
    return len(
        {
            (SLOT_BY_KEY[slot_key].day, SLOT_BY_KEY[slot_key].block)
            for slot_key in _slot_values(schedule)
        }
    )


def _current_slot_sets(
    current_schedule: dict[int, list[dict]],
) -> dict[int, set[str]]:
    return {
        client_id: {assignment["slot_key"] for assignment in assignments}
        for client_id, assignments in current_schedule.items()
    }


def _sum_expression(terms: list):
    return sum(terms) if terms else 0


def _solve_and_fix(
    *,
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    expression,
) -> bool:
    """Minimize one integer expression, then fix its best value for later stages."""
    if isinstance(expression, int):
        return True
    model.Minimize(expression)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return False
    best_value = int(solver.Value(expression))
    model.Add(expression == best_value)
    return True


def solve_schedule(
    *,
    clients: list[ClientInput],
    current_schedule: dict[int, list[dict]],
    new_client_ids: set[int] | None = None,
    edited_client_ids: set[int] | None = None,
    deleted_client_ids: set[int] | None = None,
    preferred_evenings: tuple[str, str] = ("Wednesday", "Thursday"),
    improve_mode: bool = False,
    max_seconds_per_stage: float = 4.0,
) -> ScheduleResult:
    new_client_ids = set(new_client_ids or set())
    edited_client_ids = set(edited_client_ids or set())
    deleted_client_ids = set(deleted_client_ids or set())

    if len(set(preferred_evenings)) != 2 or any(day not in DAYS for day in preferred_evenings):
        raise ValueError("preferred_evenings must contain two different schedule days.")

    client_by_id = {client.id: client for client in clients}
    if len(client_by_id) != len(clients):
        raise ValueError("Each client must have a unique ID.")

    model = cp_model.CpModel()
    x: dict[tuple[int, str], cp_model.IntVar] = {}

    for client in clients:
        valid_availability = {
            slot_key: preference
            for slot_key, preference in client.availability.items()
            if slot_key in SLOT_BY_KEY
            and preference in {PREFERENCE_BEST, PREFERENCE_ALSO_WORKS}
        }
        available_days = {SLOT_BY_KEY[key].day for key in valid_availability}
        if (
            client.sessions_per_week < 1
            or client.sessions_per_week > len(DAYS)
            or client.sessions_per_week > len(available_days)
        ):
            return ScheduleResult(feasible=False)

        for slot_key in valid_availability:
            x[(client.id, slot_key)] = model.NewBoolVar(
                f"client_{client.id}_{slot_key}"
            )

        client_vars = [x[(client.id, key)] for key in valid_availability]
        if not client_vars:
            return ScheduleResult(feasible=False)
        model.Add(sum(client_vars) == client.sessions_per_week)

        # Every weekly session for one client must be on a different day.
        for day in DAYS:
            day_vars = [
                x[(client.id, key)]
                for key in valid_availability
                if SLOT_BY_KEY[key].day == day
            ]
            if day_vars:
                model.Add(sum(day_vars) <= 1)

    occupancy: dict[str, cp_model.IntVar] = {}
    for slot in SLOTS:
        slot_vars = [
            x[(client.id, slot.key)]
            for client in clients
            if (client.id, slot.key) in x
        ]
        occupied = model.NewBoolVar(f"occupied_{slot.key}")
        occupancy[slot.key] = occupied
        if slot_vars:
            # One provider: exactly one client when this slot is occupied.
            model.Add(sum(slot_vars) == occupied)
        else:
            model.Add(occupied == 0)

    # Exact locks are hard rules, except when that same client is intentionally edited.
    for client_id, assignments in current_schedule.items():
        if client_id in deleted_client_ids or client_id not in client_by_id:
            continue
        for assignment in assignments:
            if assignment.get("locked") and client_id not in edited_client_ids:
                variable = x.get((client_id, assignment["slot_key"]))
                if variable is None:
                    return ScheduleResult(feasible=False)
                model.Add(variable == 1)

    evening_used: dict[str, cp_model.IntVar] = {}
    segment_starts: list[cp_model.IntVar] = []
    block_used: list[cp_model.IntVar] = []

    for day in DAYS:
        evening_vars = [
            occupancy[slot.key]
            for slot in SLOTS
            if slot.day == day and slot.block == "evening"
        ]
        evening_used[day] = model.NewBoolVar(f"evening_used_{day}")
        model.AddMaxEquality(evening_used[day], evening_vars)

        for block in ("afternoon", "evening"):
            ordered = sorted(
                [slot for slot in SLOTS if slot.day == day and slot.block == block],
                key=lambda slot: slot.block_index,
            )
            used = model.NewBoolVar(f"block_used_{day}_{block}")
            model.AddMaxEquality(used, [occupancy[slot.key] for slot in ordered])
            block_used.append(used)

            for index, slot in enumerate(ordered):
                start = model.NewBoolVar(f"segment_start_{slot.key}")
                current = occupancy[slot.key]
                if index == 0:
                    model.Add(start == current)
                else:
                    previous = occupancy[ordered[index - 1].key]
                    model.Add(start >= current - previous)
                    model.Add(start <= current)
                    model.Add(start + previous <= 1)
                segment_starts.append(start)

    # Only falling below two free evenings is penalized. Once two evenings are
    # free, Best times and clustering matter more than creating extra free evenings.
    evening_shortfall = model.NewIntVar(0, 2, "free_evening_shortfall")
    model.Add(evening_shortfall >= sum(evening_used.values()) - 3)

    unchanged_move_terms = []
    edited_move_terms = []
    old_sets = _current_slot_sets(current_schedule)

    for client_id, assignments in current_schedule.items():
        if client_id in deleted_client_ids or client_id not in client_by_id:
            continue
        for assignment in assignments:
            current_variable = x.get((client_id, assignment["slot_key"]))
            move_term = 1 if current_variable is None else 1 - current_variable
            if client_id in edited_client_ids:
                edited_move_terms.append(move_term)
            else:
                unchanged_move_terms.append(move_term)

    secondary_terms = [
        variable
        for (client_id, slot_key), variable in x.items()
        if client_by_id[client_id].availability.get(slot_key) == PREFERENCE_ALSO_WORKS
    ]
    preferred_evening_terms = [evening_used[day] for day in preferred_evenings]
    all_evening_terms = list(evening_used.values())

    expressions = {
        "unchanged_moves": _sum_expression(unchanged_move_terms),
        "edited_moves": _sum_expression(edited_move_terms),
        "preferred_evenings_used": _sum_expression(preferred_evening_terms),
        "free_evening_shortfall": evening_shortfall,
        "evenings_used": _sum_expression(all_evening_terms),
        "secondary": _sum_expression(secondary_terms),
        "segments": _sum_expression(segment_starts),
        "blocks": _sum_expression(block_used),
    }

    # Normal scheduling protects current appointments first. "Improve schedule"
    # intentionally optimizes evenings and clustering before minimizing movement.
    if improve_mode:
        objective_order = [
            "preferred_evenings_used",
            "free_evening_shortfall",
            "secondary",
            "segments",
            "blocks",
            "evenings_used",
            "unchanged_moves",
            "edited_moves",
        ]
    else:
        objective_order = [
            "unchanged_moves",
            "edited_moves",
            "preferred_evenings_used",
            "free_evening_shortfall",
            "secondary",
            "segments",
            "blocks",
            "evenings_used",
        ]

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds_per_stage
    solver.parameters.num_search_workers = 8

    for objective_name in objective_order:
        if not _solve_and_fix(
            model=model, solver=solver, expression=expressions[objective_name]
        ):
            return ScheduleResult(feasible=False)

    # Solve once more after all best values are fixed, so extracted values are
    # guaranteed to satisfy the complete lexicographic objective.
    model.Minimize(0)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResult(feasible=False)

    schedule: dict[int, list[str]] = {}
    preferences: dict[tuple[int, str], str] = {}
    for client in clients:
        selected: list[str] = []
        for slot_key, preference in client.availability.items():
            variable = x.get((client.id, slot_key))
            if variable is not None and solver.Value(variable) == 1:
                selected.append(slot_key)
                preferences[(client.id, slot_key)] = preference
        schedule[client.id] = sorted(
            selected,
            key=lambda key: (
                SLOT_BY_KEY[key].day_index,
                SLOT_BY_KEY[key].time_index,
            ),
        )

    moved_client_ids: list[int] = []
    moved_appointment_count = 0
    unchanged_client_moves = 0
    edited_client_moves = 0
    for client_id, old_slots in old_sets.items():
        if client_id in deleted_client_ids or client_id not in schedule:
            continue
        new_slots = set(schedule[client_id])
        removed_count = len(old_slots - new_slots)
        if removed_count:
            moved_client_ids.append(client_id)
            moved_appointment_count += removed_count
            if client_id in edited_client_ids:
                edited_client_moves += removed_count
            else:
                unchanged_client_moves += removed_count

    return ScheduleResult(
        feasible=True,
        schedule=schedule,
        preferences=preferences,
        moved_client_ids=sorted(moved_client_ids),
        moved_appointment_count=moved_appointment_count,
        unchanged_client_moves=unchanged_client_moves,
        edited_client_moves=edited_client_moves,
        free_evenings=count_free_evenings(schedule),
        preferred_evenings_free=count_preferred_evenings_free(
            schedule, preferred_evenings
        ),
        used_segments=count_segments(schedule),
        used_blocks=count_used_blocks(schedule),
        secondary_count=sum(
            preference == PREFERENCE_ALSO_WORKS
            for preference in preferences.values()
        ),
    )
