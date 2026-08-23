from __future__ import annotations

from pathlib import Path

import database
import scheduler_service as service
from solver import ScheduleResult


def _result(
    schedule: dict[int, list[str]],
    *,
    preferences: dict[tuple[int, str], str] | None = None,
    moved: list[int] | None = None,
    unchanged_moves: int = 0,
    edited_moves: int = 0,
    free_evenings: int = 5,
) -> ScheduleResult:
    return ScheduleResult(
        feasible=True,
        schedule=schedule,
        preferences=preferences or {
            (client_id, slot): "optimal"
            for client_id, slots in schedule.items()
            for slot in slots
        },
        moved_client_ids=moved or [],
        moved_appointment_count=unchanged_moves + edited_moves,
        unchanged_client_moves=unchanged_moves,
        edited_client_moves=edited_moves,
        free_evenings=free_evenings,
        preferred_evenings_free=2,
    )


def test_direct_add_is_applied_immediately(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)

    def fake_solve(**kwargs):
        new_id = next(iter(kwargs["new_client_ids"]))
        return _result({new_id: ["SUN_1400"]})

    monkeypatch.setattr(service, "solve_schedule", fake_solve)
    action = service.add_client(
        name="Eli",
        location="Room 1",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )

    assert action.added_immediately is True
    assignments = database.get_current_assignments(db_path)
    assert list(assignments.values())[0][0]["slot_key"] == "SUN_1400"
    assert database.get_client(action.client_id, db_path)["status"] == "active"
    assert database.has_draft(db_path) is False


def test_no_time_saves_waiting_client(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    monkeypatch.setattr(
        service, "solve_schedule", lambda **kwargs: ScheduleResult(feasible=False)
    )

    action = service.add_client(
        name="Miriam",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert action.success is False
    assert "saved, but no time was found" in action.message
    assert database.get_client(action.client_id, db_path)["status"] == "waiting"
    assert database.has_draft(db_path) is False


def test_partial_fit_is_reported_but_client_remains_waiting(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)

    def fake_solve(**kwargs):
        client = next(
            item for item in kwargs["clients"] if item.id in kwargs["new_client_ids"]
        )
        if client.sessions_per_week == 2:
            return ScheduleResult(feasible=False)
        return _result({client.id: ["SUN_1400"]})

    monkeypatch.setattr(service, "solve_schedule", fake_solve)
    action = service.add_client(
        name="Miriam",
        location="",
        notes="",
        sessions_per_week=2,
        availability={"SUN_1400": "optimal", "MON_1400": "secondary"},
        db_path=db_path,
    )

    assert action.success is False
    assert "1 of 2 requested sessions could be scheduled on Sunday 2:00 PM" in action.message
    assert database.get_client(action.client_id, db_path)["status"] == "waiting"
    assert database.get_current_assignments(db_path) == {}


def test_add_that_moves_existing_client_creates_draft(monkeypatch, tmp_path: Path) -> None:
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

    def fake_solve(**kwargs):
        new_ids = kwargs["new_client_ids"]
        new_id = next(iter(new_ids))
        return _result(
            {first_id: ["MON_1400"], new_id: ["SUN_1400"]},
            moved=[first_id],
            unchanged_moves=1,
        )

    monkeypatch.setattr(service, "solve_schedule", fake_solve)
    action = service.add_client(
        name="Second",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    assert action.draft_updated is True
    assert database.has_draft(db_path) is True
    # Approved schedule is untouched until approval.
    assert database.get_current_assignments(db_path)[first_id][0]["slot_key"] == "SUN_1400"


def test_failed_edit_keeps_old_information(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    client_id = database.create_waiting_client(
        name="Eli",
        location="Old room",
        notes="Old notes",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(client_id, "SUN_1400", 1)], active_client_ids={client_id}, db_path=db_path
    )
    monkeypatch.setattr(
        service, "solve_schedule", lambda **kwargs: ScheduleResult(feasible=False)
    )

    action = service.edit_client(
        client_id=client_id,
        name="Eli New",
        location="New room",
        notes="New notes",
        sessions_per_week=1,
        availability={"MON_1400": "optimal"},
        db_path=db_path,
    )
    assert action.success is False
    assert action.message == "These changes do not fit. Nothing was changed."
    saved = database.get_client(client_id, db_path)
    assert saved["name"] == "Eli"
    assert saved["location"] == "Old room"
    assert database.get_current_assignments(db_path)[client_id][0]["slot_key"] == "SUN_1400"


def test_delete_is_permanent_only_after_draft_approval(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    client_id = database.create_waiting_client(
        name="Eli",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(client_id, "SUN_1400", 0)], active_client_ids={client_id}, db_path=db_path
    )
    monkeypatch.setattr(service, "solve_schedule", lambda **kwargs: _result({}))

    action = service.delete_client(client_id=client_id, db_path=db_path)
    assert action.draft_updated is True
    assert database.get_client(client_id, db_path) is not None

    service.approve_draft(db_path)
    assert database.get_client(client_id, db_path) is None
    assert database.get_current_assignments(db_path) == {}


def test_discard_draft_leaves_approved_schedule_unchanged(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    client_id = database.create_waiting_client(
        name="Eli",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal", "MON_1400": "secondary"},
        db_path=db_path,
    )
    database.replace_approved_schedule(
        [(client_id, "SUN_1400", 0)], active_client_ids={client_id}, db_path=db_path
    )
    monkeypatch.setattr(
        service,
        "solve_schedule",
        lambda **kwargs: _result(
            {client_id: ["MON_1400"]}, moved=[client_id], edited_moves=1
        ),
    )
    service.edit_client(
        client_id=client_id,
        name="Eli",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"MON_1400": "optimal"},
        db_path=db_path,
    )
    assert database.has_draft(db_path)
    service.discard_draft(db_path)
    assert database.get_current_assignments(db_path)[client_id][0]["slot_key"] == "SUN_1400"
    assert database.has_draft(db_path) is False
