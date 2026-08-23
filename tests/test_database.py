from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import database


def test_postgres_executemany_uses_cursor() -> None:
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def executemany(self, query, params):
            calls.append((query, params))

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    params = [(1, "SUN_1400"), (2, "MON_1400")]
    connection = database._PostgresConnection(FakeConnection())

    connection.executemany(
        "INSERT INTO assignments (client_id, slot_key) VALUES (?, ?)", params
    )

    assert calls == [
        (
            "INSERT INTO assignments (client_id, slot_key) VALUES (%s, %s)",
            params,
        )
    ]


def test_fresh_database_and_defaults(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    assert database.get_preferred_evenings(db_path) == ("Wednesday", "Thursday")
    assert database.list_clients(db_path) == []


def test_old_database_migrates_without_losing_client(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            sessions_per_week INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE client_availability (
            client_id INTEGER NOT NULL,
            slot_key TEXT NOT NULL,
            preference_level TEXT NOT NULL,
            PRIMARY KEY (client_id, slot_key)
        );
        CREATE TABLE assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            slot_key TEXT NOT NULL UNIQUE,
            locked INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (client_id, slot_key)
        );
        INSERT INTO clients (name) VALUES ('Eli');
        """
    )
    conn.commit()
    conn.close()

    database.init_db(db_path)
    clients = database.list_clients(db_path)
    assert len(clients) == 1
    assert clients[0]["name"] == "Eli"
    assert clients[0]["status"] == "waiting"


def test_duplicate_names_are_case_insensitive(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    database.create_waiting_client(
        name="Eli",
        location="",
        notes="",
        sessions_per_week=1,
        availability={"SUN_1400": "optimal"},
        db_path=db_path,
    )
    with pytest.raises(ValueError, match="already exists"):
        database.create_waiting_client(
            name="eli",
            location="",
            notes="",
            sessions_per_week=1,
            availability={"MON_1400": "optimal"},
            db_path=db_path,
        )


def test_sessions_cannot_exceed_available_days(tmp_path: Path) -> None:
    db_path = tmp_path / "scheduler.db"
    database.init_db(db_path)
    with pytest.raises(ValueError, match="available on only 1 different day"):
        database.create_waiting_client(
            name="Ari",
            location="",
            notes="",
            sessions_per_week=2,
            availability={"SUN_1400": "optimal", "SUN_1430": "secondary"},
            db_path=db_path,
        )
