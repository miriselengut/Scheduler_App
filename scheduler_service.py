from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import database
from constants import (
    PREFERENCE_ALSO_WORKS,
    PREFERENCE_BEST,
    SLOT_BY_KEY,
    SLOT_KEY_TO_LABEL,
)
from solver import ClientInput, ScheduleResult, solve_schedule


@dataclass
class ActionResult:
    success: bool
    category: str
    message: str
    client_id: int | None = None
    added_immediately: bool = False
    draft_updated: bool = False
    partial_sessions: int = 0
    requested_sessions: int = 0


def _sorted_slots(slot_keys: list[str]) -> list[str]:
    return sorted(
        slot_keys,
        key=lambda key: (SLOT_BY_KEY[key].day_index, SLOT_BY_KEY[key].time_index),
    )


def _join_naturally(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _format_times(slot_keys: list[str]) -> str:
    return _join_naturally([SLOT_KEY_TO_LABEL[key] for key in _sorted_slots(slot_keys)])


def _client_inputs_from_approved(
    *,
    include_client_ids: set[int],
    db_path: str | Path,
) -> list[ClientInput]:
    clients = {item["id"]: item for item in database.list_clients(db_path)}
    availability = database.get_all_client_availability(db_path)
    result: list[ClientInput] = []
    for client_id in sorted(include_client_ids):
        client = clients.get(client_id)
        if not client:
            continue
        result.append(
            ClientInput(
                id=client_id,
                name=client["name"],
                availability=availability.get(client_id, {}),
                sessions_per_week=int(client["sessions_per_week"]),
            )
        )
    return result


def _build_effective_draft_inputs(
    db_path: str | Path,
) -> tuple[
    list[ClientInput], set[int], set[int], set[int], dict[int, dict]
]:
    current_schedule = database.get_current_assignments(db_path)
    approved_clients = {item["id"]: item for item in database.list_clients(db_path)}
    approved_availability = database.get_all_client_availability(db_path)
    changes = database.list_draft_changes(db_path)
    change_by_client = {change["client_id"]: change for change in changes}

    new_ids = {
        change["client_id"] for change in changes if change["change_type"] == "add"
    }
    edited_ids = {
        change["client_id"] for change in changes if change["change_type"] == "edit"
    }
    deleted_ids = {
        change["client_id"] for change in changes if change["change_type"] == "delete"
    }

    included_ids = (set(current_schedule) | new_ids | edited_ids) - deleted_ids
    inputs: list[ClientInput] = []
    effective_details: dict[int, dict] = {}

    for client_id in sorted(included_ids):
        approved = approved_clients.get(client_id)
        if not approved:
            continue
        change = change_by_client.get(client_id)
        if change and change["change_type"] in {"add", "edit"}:
            name = change["proposed_name"]
            sessions = int(change["proposed_sessions_per_week"])
            availability = change.get("availability", {})
            effective_details[client_id] = {
                "name": name,
                "location": change.get("proposed_location") or "",
                "notes": change.get("proposed_notes") or "",
                "sessions_per_week": sessions,
            }
        else:
            name = approved["name"]
            sessions = int(approved["sessions_per_week"])
            availability = approved_availability.get(client_id, {})
            effective_details[client_id] = approved

        inputs.append(
            ClientInput(
                id=client_id,
                name=name,
                availability=availability,
                sessions_per_week=sessions,
            )
        )

    return inputs, new_ids, edited_ids, deleted_ids, effective_details


def _build_assignment_rows(
    result: ScheduleResult,
    *,
    current_schedule: dict[int, list[dict]],
    edited_client_ids: set[int],
) -> list[tuple[int, str, int, str]]:
    """Preserve exact locks; an edited client's moved lock transfers to a new slot."""
    old_locks: dict[int, dict[str, int]] = {
        client_id: {
            assignment["slot_key"]: int(assignment.get("locked", 0))
            for assignment in assignments
        }
        for client_id, assignments in current_schedule.items()
    }

    rows: list[tuple[int, str, int, str]] = []
    for client_id, slot_keys in result.schedule.items():
        sorted_keys = _sorted_slots(slot_keys)
        lock_map = old_locks.get(client_id, {})
        locked_slots = {
            slot_key for slot_key in sorted_keys if lock_map.get(slot_key, 0) == 1
        }

        if client_id in edited_client_ids:
            old_lock_count = sum(lock_map.values())
            locks_to_transfer = max(0, old_lock_count - len(locked_slots))
            for slot_key in sorted_keys:
                if locks_to_transfer <= 0:
                    break
                if slot_key not in locked_slots:
                    locked_slots.add(slot_key)
                    locks_to_transfer -= 1

        for slot_key in sorted_keys:
            rows.append(
                (
                    client_id,
                    slot_key,
                    1 if slot_key in locked_slots else 0,
                    result.preferences.get((client_id, slot_key), ""),
                )
            )
    return rows


def _category_for_result(
    result: ScheduleResult,
    *,
    focus_client_id: int | None,
) -> str:
    if result.unchanged_client_moves > 0:
        return "Fits with changes"
    if result.free_evenings < 2:
        return "Fits, but uses another evening"
    if focus_client_id is not None:
        target_preferences = [
            result.preferences.get((focus_client_id, key))
            for key in result.schedule.get(focus_client_id, [])
        ]
        if target_preferences and all(
            preference == PREFERENCE_BEST for preference in target_preferences
        ):
            return "Fits perfectly"
    return "Fits well"


def _evening_sentence(
    result: ScheduleResult,
    preferred_evenings: tuple[str, str],
) -> str:
    first, second = preferred_evenings
    if result.preferred_evenings_free == 2:
        return f"{first} and {second} evenings stay free."
    if result.free_evenings >= 2:
        return (
            f"{result.free_evenings} evenings stay free, but one or both preferred "
            "evenings are used."
        )
    if result.free_evenings == 1:
        return "This leaves only one evening completely free."
    return "This uses all five evenings."


def _action_message(
    *,
    result: ScheduleResult,
    action: str,
    focus_client_id: int | None,
    focus_name: str | None,
    current_schedule: dict[int, list[dict]],
    preferred_evenings: tuple[str, str],
) -> str:
    evening_text = _evening_sentence(result, preferred_evenings)
    other_moved = [
        client_id
        for client_id in result.moved_client_ids
        if client_id != focus_client_id
    ]

    if action == "delete":
        return (
            f"{focus_name} will be permanently deleted when the draft is approved. "
            f"{evening_text}"
        )

    if action == "improve":
        if result.schedule == {
            client_id: _sorted_slots(
                [assignment["slot_key"] for assignment in assignments]
            )
            for client_id, assignments in current_schedule.items()
        }:
            return "The schedule is already as compact as possible. Nothing needs to move."
        return (
            "The draft schedule reduces gaps and protects free evenings where possible. "
            f"{len(result.moved_client_ids)} client schedule(s) would change. "
            "Nothing changes until you approve the draft."
        )

    if focus_client_id is None:
        movement = (
            f"{result.unchanged_client_moves} existing appointment(s) need to move. "
            if result.unchanged_client_moves
            else "No extra appointments need to move. "
        )
        return f"The remaining draft changes fit. {movement}{evening_text}"

    target_slots = result.schedule.get(focus_client_id or -1, [])
    times_text = _format_times(target_slots)
    if action == "add":
        opening = f"{focus_name} can be scheduled on {times_text}."
    else:
        current_slots = {
            assignment["slot_key"]
            for assignment in current_schedule.get(focus_client_id or -1, [])
        }
        if set(target_slots) == current_slots:
            opening = f"{focus_name}'s appointment time stays the same: {times_text}."
        else:
            opening = f"{focus_name}'s proposed schedule is {times_text}."

    if other_moved:
        movement = f"{len(other_moved)} other client schedule(s) need to move."
        review = "Review every change before approving the draft."
    else:
        movement = "No other appointments need to move."
        review = ""
    return f"{opening} {movement} {evening_text} {review}".strip()


def _solve_current_plus_client(
    client_id: int,
    *,
    db_path: str | Path,
) -> tuple[ScheduleResult, dict[int, list[dict]], tuple[str, str]]:
    current = database.get_current_assignments(db_path)
    include_ids = set(current) | {client_id}
    clients = _client_inputs_from_approved(
        include_client_ids=include_ids, db_path=db_path
    )
    preferred = database.get_preferred_evenings(db_path)
    result = solve_schedule(
        clients=clients,
        current_schedule=current,
        new_client_ids={client_id},
        preferred_evenings=preferred,
    )
    return result, current, preferred


def _find_partial_fit(
    *,
    clients: list[ClientInput],
    focus_client_id: int,
    requested_sessions: int,
    current_schedule: dict[int, list[dict]],
    preferred_evenings: tuple[str, str],
    new_client_ids: set[int] | None = None,
    edited_client_ids: set[int] | None = None,
    deleted_client_ids: set[int] | None = None,
) -> ScheduleResult | None:
    """Find the largest partial fit without changing the saved request."""
    for session_count in range(requested_sessions - 1, 0, -1):
        partial_clients = [
            ClientInput(
                id=client.id,
                name=client.name,
                availability=client.availability,
                sessions_per_week=(
                    session_count if client.id == focus_client_id else client.sessions_per_week
                ),
            )
            for client in clients
        ]
        result = solve_schedule(
            clients=partial_clients,
            current_schedule=current_schedule,
            new_client_ids=new_client_ids,
            edited_client_ids=edited_client_ids,
            deleted_client_ids=deleted_client_ids,
            preferred_evenings=preferred_evenings,
        )
        if result.feasible and len(result.schedule.get(focus_client_id, [])) == session_count:
            return result
    return None


def _partial_fit_message(
    *,
    name: str,
    focus_client_id: int,
    requested_sessions: int,
    result: ScheduleResult,
) -> str:
    slots = result.schedule.get(focus_client_id, [])
    count = len(slots)
    return (
        f"{name} was saved. {count} of {requested_sessions} requested sessions could "
        f"be scheduled on {_format_times(slots)}, but all {requested_sessions} sessions "
        "could not fit. The client remains waiting until the full request can be scheduled."
    )


def _recompute_draft(
    *,
    db_path: str | Path,
    focus_client_id: int | None,
    action: str,
    focus_name: str | None,
    force_improve: bool | None = None,
) -> ScheduleResult:
    changes = database.list_draft_changes(db_path)
    old_meta = database.get_draft_meta(db_path)
    improve_requested = (
        bool(old_meta and old_meta.get("improve_requested"))
        if force_improve is None
        else force_improve
    )

    if not changes and not improve_requested:
        database.clear_draft_solution_only(db_path)
        return ScheduleResult(feasible=True)

    clients, new_ids, edited_ids, deleted_ids, _ = _build_effective_draft_inputs(
        db_path
    )
    current = database.get_current_assignments(db_path)
    preferred = database.get_preferred_evenings(db_path)
    result = solve_schedule(
        clients=clients,
        current_schedule=current,
        new_client_ids=new_ids,
        edited_client_ids=edited_ids,
        deleted_client_ids=deleted_ids,
        preferred_evenings=preferred,
        improve_mode=improve_requested,
    )
    if not result.feasible:
        return result

    category = _category_for_result(result, focus_client_id=focus_client_id)
    if action == "improve":
        category = "Draft schedule ready"
    elif action == "delete":
        category = "Delete added to draft"

    message = _action_message(
        result=result,
        action=action,
        focus_client_id=focus_client_id,
        focus_name=focus_name,
        current_schedule=current,
        preferred_evenings=preferred,
    )

    current_simple = {
        client_id: _sorted_slots([item["slot_key"] for item in assignments])
        for client_id, assignments in current.items()
    }
    if action == "improve" and not changes and result.schedule == current_simple:
        database.clear_draft_solution_only(db_path)
        return result

    rows = _build_assignment_rows(
        result, current_schedule=current, edited_client_ids=edited_ids
    )
    database.save_draft_solution(
        category=category,
        message=message,
        free_evenings=result.free_evenings,
        preferred_evenings_free=result.preferred_evenings_free,
        moved_count=result.moved_appointment_count,
        improve_requested=improve_requested,
        assignment_rows=rows,
        db_path=db_path,
    )
    return result


def add_client(
    *,
    name: str,
    location: str,
    notes: str,
    sessions_per_week: int,
    availability: dict[str, str],
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    client_id = database.create_waiting_client(
        name=name,
        location=location,
        notes=notes,
        sessions_per_week=sessions_per_week,
        availability=availability,
        db_path=db_path,
    )
    cleaned_name = name.strip()

    if not database.has_draft(db_path):
        result, current, preferred = _solve_current_plus_client(
            client_id, db_path=db_path
        )
        if not result.feasible:
            clients = _client_inputs_from_approved(
                include_client_ids=set(current) | {client_id}, db_path=db_path
            )
            partial = _find_partial_fit(
                clients=clients,
                focus_client_id=client_id,
                requested_sessions=sessions_per_week,
                current_schedule=current,
                preferred_evenings=preferred,
                new_client_ids={client_id},
            )
            message = (
                _partial_fit_message(
                    name=cleaned_name,
                    focus_client_id=client_id,
                    requested_sessions=sessions_per_week,
                    result=partial,
                )
                if partial
                else (
                    f"{cleaned_name} was saved, but no time was found. None of the "
                    "times you selected work with the current schedule, even after "
                    "checking possible changes."
                )
            )
            return ActionResult(
                success=False,
                category="No time found",
                message=message,
                client_id=client_id,
                partial_sessions=(
                    len(partial.schedule.get(client_id, [])) if partial else 0
                ),
                requested_sessions=sessions_per_week,
            )

        if result.unchanged_client_moves == 0:
            rows = _build_assignment_rows(
                result, current_schedule=current, edited_client_ids=set()
            )
            database.replace_approved_schedule(
                [(client, slot, locked) for client, slot, locked, _ in rows],
                active_client_ids=result.schedule,
                db_path=db_path,
            )
            category = _category_for_result(result, focus_client_id=client_id)
            message = _action_message(
                result=result,
                action="add",
                focus_client_id=client_id,
                focus_name=cleaned_name,
                current_schedule=current,
                preferred_evenings=preferred,
            )
            return ActionResult(
                success=True,
                category=category,
                message=message,
                client_id=client_id,
                added_immediately=True,
            )

    database.upsert_draft_change(
        client_id=client_id,
        change_type="add",
        proposed_name=cleaned_name,
        proposed_location=location,
        proposed_notes=notes,
        proposed_sessions_per_week=sessions_per_week,
        proposed_availability=availability,
        db_path=db_path,
    )
    result = _recompute_draft(
        db_path=db_path,
        focus_client_id=client_id,
        action="add",
        focus_name=cleaned_name,
    )
    if not result.feasible:
        clients, new_ids, edited_ids, deleted_ids, _ = _build_effective_draft_inputs(
            db_path
        )
        current = database.get_current_assignments(db_path)
        preferred = database.get_preferred_evenings(db_path)
        partial = _find_partial_fit(
            clients=clients,
            focus_client_id=client_id,
            requested_sessions=sessions_per_week,
            current_schedule=current,
            preferred_evenings=preferred,
            new_client_ids=new_ids,
            edited_client_ids=edited_ids,
            deleted_client_ids=deleted_ids,
        )
        database.remove_draft_change_by_client(client_id, db_path=db_path)
        _recompute_draft(
            db_path=db_path,
            focus_client_id=None,
            action="draft",
            focus_name=None,
        )
        message = (
            _partial_fit_message(
                name=cleaned_name,
                focus_client_id=client_id,
                requested_sessions=sessions_per_week,
                result=partial,
            )
            if partial
            else (
                f"{cleaned_name} was saved, but no time was found. None of the "
                "times you selected work with the current schedule and draft changes."
            )
        )
        return ActionResult(
            success=False,
            category="No time found",
            message=message,
            client_id=client_id,
            partial_sessions=(
                len(partial.schedule.get(client_id, [])) if partial else 0
            ),
            requested_sessions=sessions_per_week,
        )

    meta = database.get_draft_meta(db_path) or {}
    return ActionResult(
        success=True,
        category=meta.get("category", "Added to draft"),
        message=meta.get("message", "The client was added to the draft schedule."),
        client_id=client_id,
        draft_updated=True,
    )


def add_partial_client_to_draft(
    *,
    client_id: int,
    sessions_per_week: int,
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    client = database.get_client(client_id, db_path)
    if not client:
        raise ValueError("Client not found.")
    requested_sessions = int(client["sessions_per_week"])
    if sessions_per_week < 1 or sessions_per_week >= requested_sessions:
        raise ValueError("Choose a valid partial session count.")

    availability = database.get_client_availability(client_id, db_path)
    database.upsert_draft_change(
        client_id=client_id,
        change_type="add",
        proposed_name=client["name"],
        proposed_location=client["location"],
        proposed_notes=client["notes"],
        proposed_sessions_per_week=sessions_per_week,
        proposed_availability=availability,
        db_path=db_path,
    )
    result = _recompute_draft(
        db_path=db_path,
        focus_client_id=client_id,
        action="add",
        focus_name=client["name"],
    )
    if not result.feasible:
        database.remove_draft_change_by_client(client_id, db_path=db_path)
        _recompute_draft(
            db_path=db_path,
            focus_client_id=None,
            action="draft",
            focus_name=None,
        )
        return ActionResult(
            success=False,
            category="Partial schedule no longer fits",
            message="The schedule changed. Try saving the client again.",
            client_id=client_id,
        )

    meta = database.get_draft_meta(db_path) or {}
    return ActionResult(
        success=True,
        category=meta.get("category", "Added to draft"),
        message=(
            f"{sessions_per_week} of {requested_sessions} requested sessions were "
            "added to Review Changes."
        ),
        client_id=client_id,
        draft_updated=True,
    )


def edit_client(
    *,
    client_id: int,
    name: str,
    location: str,
    notes: str,
    sessions_per_week: int,
    availability: dict[str, str],
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    client = database.get_client(client_id, db_path)
    if not client:
        raise ValueError("Client not found.")
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Enter the client's name.")
    if database.name_exists(
        cleaned_name, exclude_client_id=client_id, db_path=db_path
    ):
        raise ValueError(
            f"A client named {cleaned_name} already exists. Please use a different name."
        )
    database.validate_client_schedule_options(availability, sessions_per_week)

    previous = database.get_draft_change(client_id, db_path)
    if previous and previous["change_type"] == "delete":
        raise ValueError("Remove this client's delete request from the draft before editing.")

    database.upsert_draft_change(
        client_id=client_id,
        change_type="edit",
        proposed_name=cleaned_name,
        proposed_location=location,
        proposed_notes=notes,
        proposed_sessions_per_week=sessions_per_week,
        proposed_availability=availability,
        db_path=db_path,
    )
    result = _recompute_draft(
        db_path=db_path,
        focus_client_id=client_id,
        action="edit",
        focus_name=cleaned_name,
    )
    if not result.feasible:
        database.restore_draft_change(previous, client_id=client_id, db_path=db_path)
        if database.list_draft_changes(db_path) or (
            database.get_draft_meta(db_path)
            and database.get_draft_meta(db_path).get("improve_requested")
        ):
            old_meta = database.get_draft_meta(db_path)
            _recompute_draft(
                db_path=db_path,
                focus_client_id=None,
                action="improve" if old_meta and old_meta.get("improve_requested") else "draft",
                focus_name=None,
            )
        else:
            database.clear_draft_solution_only(db_path)
        return ActionResult(
            success=False,
            category="No time found",
            message="These changes do not fit. Nothing was changed.",
            client_id=client_id,
        )

    meta = database.get_draft_meta(db_path) or {}
    return ActionResult(
        success=True,
        category=meta.get("category", "Added to draft"),
        message=meta.get("message", "The changes were added to the draft."),
        client_id=client_id,
        draft_updated=True,
    )


def delete_client(
    *,
    client_id: int,
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    client = database.get_client(client_id, db_path)
    if not client:
        raise ValueError("Client not found.")

    previous = database.get_draft_change(client_id, db_path)
    database.upsert_draft_change(
        client_id=client_id,
        change_type="delete",
        db_path=db_path,
    )
    result = _recompute_draft(
        db_path=db_path,
        focus_client_id=client_id,
        action="delete",
        focus_name=client["name"],
    )
    if not result.feasible:
        database.restore_draft_change(previous, client_id=client_id, db_path=db_path)
        raise RuntimeError("The remaining schedule could not be rebuilt.")

    meta = database.get_draft_meta(db_path) or {}
    return ActionResult(
        success=True,
        category=meta.get("category", "Delete added to draft"),
        message=meta.get("message", "The delete request was added to the draft."),
        client_id=client_id,
        draft_updated=True,
    )


def request_improve_schedule(
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    result = _recompute_draft(
        db_path=db_path,
        focus_client_id=None,
        action="improve",
        focus_name=None,
        force_improve=True,
    )
    if not result.feasible:
        return ActionResult(
            success=False,
            category="No improved schedule found",
            message="The current locks and availability do not allow another schedule.",
        )
    meta = database.get_draft_meta(db_path)
    if not meta:
        return ActionResult(
            success=True,
            category="Schedule already improved",
            message="The schedule is already as compact as possible. Nothing needs to move.",
        )
    return ActionResult(
        success=True,
        category=meta.get("category", "Draft schedule ready"),
        message=meta.get("message", "An improved schedule was added to the draft."),
        draft_updated=True,
    )


def remove_draft_change(
    change_id: int,
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    changes = database.list_draft_changes(db_path)
    target = next((change for change in changes if change["id"] == change_id), None)
    if not target:
        raise ValueError("Draft change not found.")
    database.remove_draft_change(change_id, db_path)
    meta = database.get_draft_meta(db_path)
    improve_requested = bool(meta and meta.get("improve_requested"))

    if not database.list_draft_changes(db_path) and not improve_requested:
        database.clear_draft_solution_only(db_path)
        return ActionResult(
            success=True,
            category="Draft updated",
            message="The change was removed. There are no draft changes left.",
        )

    result = _recompute_draft(
        db_path=db_path,
        focus_client_id=None,
        action="improve" if improve_requested else "draft",
        focus_name=None,
    )
    if not result.feasible:
        raise RuntimeError("The remaining draft could not be recalculated.")
    return ActionResult(
        success=True,
        category="Draft updated",
        message="The change was removed and the draft schedule was recalculated.",
        draft_updated=True,
    )


def discard_draft(db_path: str | Path = database.DEFAULT_DB_PATH) -> ActionResult:
    database.clear_draft(db_path)
    return ActionResult(
        success=True,
        category="Draft discarded",
        message="The approved schedule was not changed.",
    )


def approve_draft(db_path: str | Path = database.DEFAULT_DB_PATH) -> ActionResult:
    database.approve_draft(db_path)
    return ActionResult(
        success=True,
        category="Draft approved",
        message="The new schedule is now active.",
    )


def update_preferred_evenings(
    *,
    first: str,
    second: str,
    db_path: str | Path = database.DEFAULT_DB_PATH,
) -> ActionResult:
    database.set_preferred_evenings(first, second, db_path)
    if database.has_draft(db_path):
        result = _recompute_draft(
            db_path=db_path,
            focus_client_id=None,
            action="improve",
            focus_name=None,
        )
        if not result.feasible:
            return ActionResult(
                success=False,
                category="Settings saved",
                message=(
                    "The preferred evenings were saved, but the current draft could not "
                    "be recalculated. Remove a draft change and try again."
                ),
            )
        return ActionResult(
            success=True,
            category="Settings saved",
            message="The preferred evenings were saved and the draft was recalculated.",
            draft_updated=True,
        )
    return ActionResult(
        success=True,
        category="Settings saved",
        message=f"The scheduler will try to keep {first} and {second} evenings free.",
    )
