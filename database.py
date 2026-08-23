from __future__ import annotations

import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from constants import DAYS, SLOT_BY_KEY
from project_version import EXPECTED_BUILD

DEFAULT_DB_PATH = None


def _supabase_db_url() -> str:
    value = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get("SUPABASE_DB_URL")
    except Exception:
        value = None
    if not value:
        raise RuntimeError(
            "Missing SUPABASE_DB_URL. Add the Supabase connection string to "
            "Streamlit Secrets or your local environment."
        )
    return str(value)


class _PostgresConnection:
    """Small compatibility layer for the existing parameterized SQL."""

    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def _sql(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params=()):
        return self._connection.execute(self._sql(query), params)

    def executemany(self, query: str, params):
        with self._connection.cursor() as cursor:
            return cursor.executemany(self._sql(query), params)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


@contextmanager
def connect(db_path: str | Path | None = DEFAULT_DB_PATH):
    if db_path is None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "The psycopg package is required for the Supabase connection."
            ) from exc
        raw_connection = psycopg.connect(_supabase_db_url(), row_factory=dict_row)
        connection = _PostgresConnection(raw_connection)
    else:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone() is not None


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name not in _column_names(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _migrate_assignments(conn: sqlite3.Connection) -> None:
    columns = _column_names(conn, "assignments")
    if not columns or "id" in columns:
        return

    locked_expression = "COALESCE(locked, 0)" if "locked" in columns else "0"
    updated_expression = (
        "COALESCE(updated_at, CURRENT_TIMESTAMP)"
        if "updated_at" in columns
        else "CURRENT_TIMESTAMP"
    )

    conn.execute("ALTER TABLE assignments RENAME TO assignments_legacy")
    conn.executescript(
        """
        CREATE TABLE assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            slot_key TEXT NOT NULL UNIQUE,
            locked INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (client_id, slot_key),
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        f"""
        INSERT INTO assignments (client_id, slot_key, locked, updated_at)
        SELECT client_id, slot_key, {locked_expression}, {updated_expression}
        FROM assignments_legacy
        """
    )
    conn.execute("DROP TABLE assignments_legacy")


def init_db(db_path: str | Path | None = DEFAULT_DB_PATH) -> None:
    if db_path is None:
        with connect() as conn:
            conn.execute("SELECT 1 FROM clients LIMIT 1")
        return
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                sessions_per_week INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'waiting')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS client_availability (
                client_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                preference_level TEXT NOT NULL
                    CHECK (preference_level IN ('optimal', 'secondary')),
                PRIMARY KEY (client_id, slot_key),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL UNIQUE,
                locked INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (client_id, slot_key),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS draft_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL UNIQUE,
                change_type TEXT NOT NULL
                    CHECK (change_type IN ('add', 'edit', 'delete')),
                proposed_name TEXT,
                proposed_location TEXT,
                proposed_notes TEXT,
                proposed_sessions_per_week INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS draft_change_availability (
                change_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                preference_level TEXT NOT NULL
                    CHECK (preference_level IN ('optimal', 'secondary')),
                PRIMARY KEY (change_id, slot_key),
                FOREIGN KEY (change_id) REFERENCES draft_changes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS draft_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                free_evenings INTEGER NOT NULL,
                preferred_evenings_free INTEGER NOT NULL,
                moved_count INTEGER NOT NULL,
                improve_requested INTEGER NOT NULL DEFAULT 0,
                build_version TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS draft_assignments (
                client_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL UNIQUE,
                locked INTEGER NOT NULL DEFAULT 0,
                preference_level TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (client_id, slot_key),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );
            """
        )

        # Safe upgrades from prior releases.
        _add_column_if_missing(
            conn, "clients", "sessions_per_week", "INTEGER NOT NULL DEFAULT 1"
        )
        _add_column_if_missing(conn, "clients", "active", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(
            conn,
            "clients",
            "status",
            "TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'waiting'))",
        )
        _add_column_if_missing(conn, "clients", "updated_at", "TEXT")
        conn.execute(
            "UPDATE clients SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
        )
        _migrate_assignments(conn)

        duplicate_name = conn.execute(
            """
            SELECT name
            FROM clients
            GROUP BY name COLLATE NOCASE
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate_name is None:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_name_nocase "
                "ON clients(name COLLATE NOCASE)"
            )

        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('preferred_evening_1', 'Wednesday')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('preferred_evening_2', 'Thursday')"
        )

        # Older saved-but-unscheduled clients should be shown as waiting.
        conn.execute(
            """
            UPDATE clients
            SET status = CASE
                WHEN EXISTS (
                    SELECT 1 FROM assignments a WHERE a.client_id = clients.id
                ) THEN 'active'
                ELSE 'waiting'
            END
            """
        )


def validate_client_schedule_options(
    availability: dict[str, str],
    sessions_per_week: int,
) -> None:
    if not 1 <= sessions_per_week <= len(DAYS):
        raise ValueError(f"Sessions each week must be between 1 and {len(DAYS)}.")
    if not availability:
        raise ValueError("Choose at least one Best time or Also works time.")

    invalid_slots = [slot_key for slot_key in availability if slot_key not in SLOT_BY_KEY]
    if invalid_slots:
        raise ValueError("One or more selected times are not valid schedule times.")

    invalid_preferences = [
        preference
        for preference in availability.values()
        if preference not in {"optimal", "secondary"}
    ]
    if invalid_preferences:
        raise ValueError("Each selected time must be Best time or Also works.")

    available_days = {SLOT_BY_KEY[slot_key].day for slot_key in availability}
    if sessions_per_week > len(available_days):
        raise ValueError(
            f"This client needs {sessions_per_week} sessions, but is available on only "
            f"{len(available_days)} different day(s). Add times on another day or lower "
            "the number of sessions."
        )


def name_exists(
    name: str,
    *,
    exclude_client_id: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    cleaned_name = name.strip()
    if not cleaned_name:
        return False
    query = "SELECT 1 FROM clients WHERE LOWER(name) = LOWER(?)"
    params: list[object] = [cleaned_name]
    if exclude_client_id is not None:
        query += " AND id <> ?"
        params.append(exclude_client_id)
    query += " LIMIT 1"
    with connect(db_path) as conn:
        return conn.execute(query, tuple(params)).fetchone() is not None


def create_waiting_client(
    *,
    name: str,
    location: str,
    notes: str,
    sessions_per_week: int,
    availability: dict[str, str],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Enter the client's name.")
    if name_exists(cleaned_name, db_path=db_path):
        raise ValueError(
            f"A client named {cleaned_name} already exists. Please use a different name."
        )
    validate_client_schedule_options(availability, sessions_per_week)

    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO clients
                (name, location, notes, sessions_per_week, active, status)
            VALUES (?, ?, ?, ?, true, 'waiting')
            """,
            (cleaned_name, location.strip(), notes.strip(), sessions_per_week),
        )
        if db_path is None:
            client_id = int(
                conn.execute("SELECT currval(pg_get_serial_sequence('clients', 'id'))")
                .fetchone()["currval"]
            )
        else:
            client_id = int(cursor.lastrowid)
        _replace_availability_conn(conn, client_id, availability)
        return client_id


def _replace_availability_conn(
    conn: sqlite3.Connection,
    client_id: int,
    availability: dict[str, str],
) -> None:
    conn.execute("DELETE FROM client_availability WHERE client_id = ?", (client_id,))
    conn.executemany(
        """
        INSERT INTO client_availability (client_id, slot_key, preference_level)
        VALUES (?, ?, ?)
        """,
        [
            (client_id, slot_key, preference)
            for slot_key, preference in availability.items()
        ],
    )


def get_client(
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return dict(row) if row else None


def list_clients(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.*,
                   COUNT(a.id) AS scheduled_sessions
            FROM clients c
            LEFT JOIN assignments a ON a.client_id = c.id
            GROUP BY c.id
            ORDER BY LOWER(c.name)
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_client_availability(
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, str]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT slot_key, preference_level
            FROM client_availability
            WHERE client_id = ?
            """,
            (client_id,),
        ).fetchall()
        return {row["slot_key"]: row["preference_level"] for row in rows}


def get_all_client_availability(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[int, dict[str, str]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT client_id, slot_key, preference_level FROM client_availability"
        ).fetchall()
        result: dict[int, dict[str, str]] = {}
        for row in rows:
            result.setdefault(row["client_id"], {})[row["slot_key"]] = row[
                "preference_level"
            ]
        return result


def get_current_assignments(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[int, list[dict]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.client_id, a.slot_key, a.locked, c.name
            FROM assignments a
            JOIN clients c ON c.id = a.client_id
            ORDER BY a.slot_key
            """
        ).fetchall()
        result: dict[int, list[dict]] = {}
        for row in rows:
            result.setdefault(row["client_id"], []).append(dict(row))
        return result


def set_assignment_lock(
    assignment_id: int,
    locked: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE assignments
            SET locked = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (bool(locked), assignment_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Appointment not found.")


def replace_approved_schedule(
    rows: Iterable[tuple[int, str, int]],
    *,
    active_client_ids: Iterable[int],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    rows = list(rows)
    active_ids = set(active_client_ids)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM assignments")
        conn.executemany(
            """
            INSERT INTO assignments (client_id, slot_key, locked)
            VALUES (?, ?, ?)
            """,
            [(client_id, slot_key, bool(locked)) for client_id, slot_key, locked in rows],
        )
        if active_ids:
            placeholders = ",".join("?" for _ in active_ids)
            conn.execute(
                f"UPDATE clients SET status='active', updated_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                tuple(active_ids),
            )


def get_preferred_evenings(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[str, str]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT key, value FROM settings
            WHERE key IN ('preferred_evening_1', 'preferred_evening_2')
            """
        ).fetchall()
        values = {row["key"]: row["value"] for row in rows}
    first = values.get("preferred_evening_1", "Wednesday")
    second = values.get("preferred_evening_2", "Thursday")
    if first not in DAYS or second not in DAYS or first == second:
        return "Wednesday", "Thursday"
    return first, second


def set_preferred_evenings(
    first: str,
    second: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    if first not in DAYS or second not in DAYS:
        raise ValueError("Choose two valid evenings.")
    if first == second:
        raise ValueError("Choose two different evenings.")
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES ('preferred_evening_1', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (first,),
        )
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES ('preferred_evening_2', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (second,),
        )


def get_draft_change(
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM draft_changes WHERE client_id = ?", (client_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        availability_rows = conn.execute(
            """
            SELECT slot_key, preference_level
            FROM draft_change_availability
            WHERE change_id = ?
            """,
            (row["id"],),
        ).fetchall()
        result["availability"] = {
            item["slot_key"]: item["preference_level"] for item in availability_rows
        }
        return result


def list_draft_changes(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT dc.*, c.name AS current_name
            FROM draft_changes dc
            JOIN clients c ON c.id = dc.client_id
            ORDER BY dc.id
            """
        ).fetchall()
        result: list[dict] = []
        for row in rows:
            item = dict(row)
            availability_rows = conn.execute(
                """
                SELECT slot_key, preference_level
                FROM draft_change_availability
                WHERE change_id = ?
                """,
                (row["id"],),
            ).fetchall()
            item["availability"] = {
                value["slot_key"]: value["preference_level"]
                for value in availability_rows
            }
            result.append(item)
        return result


def upsert_draft_change(
    *,
    client_id: int,
    change_type: str,
    proposed_name: str | None = None,
    proposed_location: str | None = None,
    proposed_notes: str | None = None,
    proposed_sessions_per_week: int | None = None,
    proposed_availability: dict[str, str] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    if change_type not in {"add", "edit", "delete"}:
        raise ValueError("Unknown draft change type.")
    if change_type in {"add", "edit"}:
        if proposed_name is None or proposed_sessions_per_week is None:
            raise ValueError("Client details are required for this draft change.")
        validate_client_schedule_options(
            proposed_availability or {}, proposed_sessions_per_week
        )

    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id, change_type FROM draft_changes WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        effective_type = change_type
        if existing and existing["change_type"] == "add" and change_type == "edit":
            effective_type = "add"

        if existing:
            change_id = int(existing["id"])
            conn.execute(
                """
                UPDATE draft_changes
                SET change_type=?, proposed_name=?, proposed_location=?, proposed_notes=?,
                    proposed_sessions_per_week=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    effective_type,
                    proposed_name.strip() if proposed_name is not None else None,
                    proposed_location.strip() if proposed_location is not None else None,
                    proposed_notes.strip() if proposed_notes is not None else None,
                    proposed_sessions_per_week,
                    change_id,
                ),
            )
            conn.execute(
                "DELETE FROM draft_change_availability WHERE change_id = ?",
                (change_id,),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO draft_changes
                    (client_id, change_type, proposed_name, proposed_location,
                     proposed_notes, proposed_sessions_per_week)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    effective_type,
                    proposed_name.strip() if proposed_name is not None else None,
                    proposed_location.strip() if proposed_location is not None else None,
                    proposed_notes.strip() if proposed_notes is not None else None,
                    proposed_sessions_per_week,
                ),
            )
            if db_path is None:
                change_id = int(
                    conn.execute(
                        "SELECT currval(pg_get_serial_sequence('draft_changes', 'id'))"
                    ).fetchone()["currval"]
                )
            else:
                change_id = int(cursor.lastrowid)

        if proposed_availability:
            conn.executemany(
                """
                INSERT INTO draft_change_availability
                    (change_id, slot_key, preference_level)
                VALUES (?, ?, ?)
                """,
                [
                    (change_id, slot_key, preference)
                    for slot_key, preference in proposed_availability.items()
                ],
            )
        return change_id


def restore_draft_change(
    previous: dict | None,
    *,
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    if previous is None:
        remove_draft_change_by_client(client_id, db_path=db_path)
        return
    upsert_draft_change(
        client_id=client_id,
        change_type=previous["change_type"],
        proposed_name=previous.get("proposed_name"),
        proposed_location=previous.get("proposed_location"),
        proposed_notes=previous.get("proposed_notes"),
        proposed_sessions_per_week=previous.get("proposed_sessions_per_week"),
        proposed_availability=previous.get("availability", {}),
        db_path=db_path,
    )


def remove_draft_change(
    change_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM draft_changes WHERE id = ?", (change_id,))


def remove_draft_change_by_client(
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM draft_changes WHERE client_id = ?", (client_id,))


def get_draft_meta(db_path: str | Path = DEFAULT_DB_PATH) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM draft_meta WHERE id = 1").fetchone()
        return dict(row) if row else None


def get_draft_assignments(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[int, list[dict]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT da.client_id, da.slot_key, da.locked, da.preference_level,
                   COALESCE(dc.proposed_name, c.name) AS name
            FROM draft_assignments da
            JOIN clients c ON c.id = da.client_id
            LEFT JOIN draft_changes dc ON dc.client_id = da.client_id
            ORDER BY da.slot_key
            """
        ).fetchall()
        result: dict[int, list[dict]] = {}
        for row in rows:
            result.setdefault(row["client_id"], []).append(dict(row))
        return result


def has_draft(db_path: str | Path = DEFAULT_DB_PATH) -> bool:
    with connect(db_path) as conn:
        change_exists = conn.execute("SELECT 1 FROM draft_changes LIMIT 1").fetchone()
        meta_exists = conn.execute("SELECT 1 FROM draft_meta WHERE id=1").fetchone()
        return change_exists is not None or meta_exists is not None


def save_draft_solution(
    *,
    category: str,
    message: str,
    free_evenings: int,
    preferred_evenings_free: int,
    moved_count: int,
    improve_requested: bool,
    assignment_rows: Iterable[tuple[int, str, int, str]],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    assignment_rows = list(assignment_rows)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO draft_meta
                (id, category, message, free_evenings, preferred_evenings_free,
                 moved_count, improve_requested, build_version, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                category=excluded.category,
                message=excluded.message,
                free_evenings=excluded.free_evenings,
                preferred_evenings_free=excluded.preferred_evenings_free,
                moved_count=excluded.moved_count,
                improve_requested=excluded.improve_requested,
                build_version=excluded.build_version,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                category,
                message,
                free_evenings,
                preferred_evenings_free,
                moved_count,
                bool(improve_requested),
                EXPECTED_BUILD,
            ),
        )
        conn.execute("DELETE FROM draft_assignments")
        conn.executemany(
            """
            INSERT INTO draft_assignments
                (client_id, slot_key, locked, preference_level)
            VALUES (?, ?, ?, ?)
            """,
            [
                (client_id, slot_key, bool(locked), preference_level)
                for client_id, slot_key, locked, preference_level in assignment_rows
            ],
        )


def clear_draft_solution_only(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM draft_assignments")
        conn.execute("DELETE FROM draft_meta")


def clear_draft(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM draft_assignments")
        conn.execute("DELETE FROM draft_meta")
        conn.execute("DELETE FROM draft_changes")


def approve_draft(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        meta = conn.execute("SELECT * FROM draft_meta WHERE id=1").fetchone()
        if meta is None:
            raise ValueError("There is no draft schedule to approve.")

        changes = conn.execute("SELECT * FROM draft_changes ORDER BY id").fetchall()
        for change in changes:
            client_id = int(change["client_id"])
            if change["change_type"] == "delete":
                continue
            conn.execute(
                """
                UPDATE clients
                SET name=?, location=?, notes=?, sessions_per_week=?,
                    status='active', active=true, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    change["proposed_name"],
                    change["proposed_location"] or "",
                    change["proposed_notes"] or "",
                    change["proposed_sessions_per_week"],
                    client_id,
                ),
            )
            conn.execute(
                "DELETE FROM client_availability WHERE client_id=?", (client_id,)
            )
            availability_rows = conn.execute(
                """
                SELECT slot_key, preference_level
                FROM draft_change_availability
                WHERE change_id=?
                """,
                (change["id"],),
            ).fetchall()
            conn.executemany(
                """
                INSERT INTO client_availability
                    (client_id, slot_key, preference_level)
                VALUES (?, ?, ?)
                """,
                [
                    (client_id, row["slot_key"], row["preference_level"])
                    for row in availability_rows
                ],
            )

        delete_ids = [
            int(change["client_id"])
            for change in changes
            if change["change_type"] == "delete"
        ]
        if delete_ids:
            placeholders = ",".join("?" for _ in delete_ids)
            conn.execute(
                f"DELETE FROM clients WHERE id IN ({placeholders})", tuple(delete_ids)
            )

        rows = conn.execute(
            "SELECT client_id, slot_key, locked FROM draft_assignments"
        ).fetchall()
        conn.execute("DELETE FROM assignments")
        conn.executemany(
            """
            INSERT INTO assignments (client_id, slot_key, locked)
            VALUES (?, ?, ?)
            """,
            [
                (row["client_id"], row["slot_key"], bool(row["locked"]))
                for row in rows
            ],
        )

        scheduled_ids = {int(row["client_id"]) for row in rows}
        if scheduled_ids:
            placeholders = ",".join("?" for _ in scheduled_ids)
            conn.execute(
                f"UPDATE clients SET status='active', updated_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                tuple(scheduled_ids),
            )

        conn.execute("DELETE FROM draft_assignments")
        conn.execute("DELETE FROM draft_meta")
        conn.execute("DELETE FROM draft_changes")


def permanently_delete_waiting_client(
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with connect(db_path) as conn:
        scheduled = conn.execute(
            "SELECT 1 FROM assignments WHERE client_id=?", (client_id,)
        ).fetchone()
        if scheduled:
            raise ValueError("Scheduled clients must be deleted through the Draft Schedule.")
        conn.execute("DELETE FROM clients WHERE id=?", (client_id,))
