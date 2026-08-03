from __future__ import annotations

from pathlib import Path

import database
import scheduler_service as service


def test_free_slot_adds_immediately_with_actual_solver(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    result = service.add_client(
        name="Eli",
        location="Room A",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert result.success
    assert result.added_immediately
    assert database.get_current_assignments(db_path)[result.client_id][0]["slot_key"] == "SUN_1400"


def test_old_waiting_client_does_not_block_new_client(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    waiting_id = database.create_waiting_client(
        name="Waiting",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert database.get_client(waiting_id, db_path)["status"] == "waiting"

    result = service.add_client(
        name="New Client",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"MON_1400": "optimal"},
        db_path=db_path,
    )
    assert result.success
    assert result.added_immediately
    assert waiting_id not in database.get_current_assignments(db_path)


def test_needed_rearrangement_creates_one_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    first_id = database.create_waiting_client(
        name="First",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal", "MON_1400": "secondary"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(first_id, "SUN_1400", 0)], active_client_ids={first_id}, db_path=db_path
    )

    result = service.add_client(
        name="Second",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert result.success
    assert result.draft_updated
    assert database.get_current_assignments(db_path)[first_id][0]["slot_key"] == "SUN_1400"
    draft = database.get_draft_assignments(db_path)
    assert {item["slot_key"] for item in draft[first_id]} == {"MON_1400"}
    assert len(database.list_draft_changes(db_path)) == 1


def test_multi_session_client_uses_different_days(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    result = service.add_client(
        name="Two Sessions",
        location="",
        notes="",
        sessions_per_week=2,
        availability={
            "SUN_1400": "optimal",
            "SUN_1430": "optimal",
            "MON_1400": "optimal",
        },
        db_path=db_path,
    )
    assert result.success
    assignments = database.get_current_assignments(db_path)[result.client_id]
    assert len(assignments) == 2
    days = {item["slot_key"].split("_")[0] for item in assignments}
    assert days == {"SUN", "MON"}


def test_edited_lock_moves_and_stays_locked_after_approval(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    client_id = database.create_waiting_client(
        name="Locked",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(client_id, "SUN_1400", 1)], active_client_ids={client_id}, db_path=db_path
    )

    result = service.edit_client(
        client_id=client_id,
        name="Locked",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"MON_1400": "optimal"},
        db_path=db_path,
    )
    assert result.success
    draft_assignment = database.get_draft_assignments(db_path)[client_id][0]
    assert draft_assignment["slot_key"] == "MON_1400"
    assert draft_assignment["locked"] == 1

    service.approve_draft(db_path)
    approved = database.get_current_assignments(db_path)[client_id][0]
    assert approved["slot_key"] == "MON_1400"
    assert approved["locked"] == 1


def test_multiple_changes_share_one_draft_and_approve_together(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    first_id = database.create_waiting_client(
        name="First",
        location="Old",
        notes="",
        sessions_per_week=1,
        availability={
            "SUN_1400": "optimal",
            "MON_1400": "secondary",
            "TUE_1400": "secondary",
        },
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(first_id, "SUN_1400", 0)], active_client_ids={first_id}, db_path=db_path
    )

    add_result = service.add_client(
        name="Second",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert add_result.draft_updated

    edit_result = service.edit_client(
        client_id=first_id,
        name="First Updated",
        location="New",
        notes="Updated",
        sessions_per_week=1,
        availability={"TUE_1400": "optimal"},
        db_path=db_path,
    )
    assert edit_result.draft_updated
    assert len(database.list_draft_changes(db_path)) == 2

    service.approve_draft(db_path)
    first = database.get_client(first_id, db_path)
    assert first["name"] == "First Updated"
    assert first["location"] == "New"
    approved = database.get_current_assignments(db_path)
    assert approved[first_id][0]["slot_key"] == "TUE_1400"
    assert len(approved) == 2


def test_failed_change_does_not_damage_existing_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    first_id = database.create_waiting_client(
        name="First",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal", "MON_1400": "secondary"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(first_id, "SUN_1400", 0)], active_client_ids={first_id}, db_path=db_path
    )
    add = service.add_client(
        name="Second",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert add.draft_updated
    before = database.get_draft_assignments(db_path)

    failed = service.edit_client(
        client_id=first_id,
        name="First",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert failed.success is False
    assert database.get_draft_assignments(db_path) == before
    assert len(database.list_draft_changes(db_path)) == 1


def test_removing_one_draft_change_recalculates_remaining_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    first_id = database.create_waiting_client(
        name="First",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal", "MON_1400": "secondary"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(first_id, "SUN_1400", 0)], active_client_ids={first_id}, db_path=db_path
    )
    added = service.add_client(
        name="Second",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert added.draft_updated
    change = database.list_draft_changes(db_path)[0]
    service.remove_draft_change(change["id"], db_path)
    assert database.has_draft(db_path) is False
    assert database.get_current_assignments(db_path)[first_id][0]["slot_key"] == "SUN_1400"
    assert database.get_client(added.client_id, db_path)["status"] == "waiting"


def test_deleted_name_can_be_used_again_after_approval(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    original = service.add_client(
        name="Eli",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    service.delete_client(client_id=original.client_id, db_path=db_path)
    service.approve_draft(db_path)

    replacement = service.add_client(
        name="Eli",
        location="New room",
        notes="",
        sessions_per_week=1,
        availability={"MON_1400": "optimal"},
        db_path=db_path,
    )
    assert replacement.success
    assert replacement.client_id != original.client_id
