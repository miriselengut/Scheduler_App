from __future__ import annotations

import sqlite3
from pathlib import Path

import database
from seed_demo_database import DEMO_CLIENTS, seed_demo_database


def test_demo_database_contains_valid_examples(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"
    seed_demo_database(db_path, overwrite=False)

    clients = database.list_clients(db_path)
    assignments = database.get_current_assignments(db_path)

    assert len(clients) == len(DEMO_CLIENTS) == 8
    assert sum(len(items) for items in assignments.values()) == 9
    assert all(client["status"] == "active" for client in clients)
    assert database.get_preferred_evenings(db_path) == ("Wednesday", "Thursday")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM draft_changes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM draft_assignments").fetchone()[0] == 0


def test_demo_database_will_not_overwrite_without_force(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"
    seed_demo_database(db_path, overwrite=False)

    try:
        seed_demo_database(db_path, overwrite=False)
    except FileExistsError as exc:
        assert "--force" in str(exc)
    else:
        raise AssertionError("Existing data should not be overwritten without force.")
