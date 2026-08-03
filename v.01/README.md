from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).with_name("scheduler.db")


@contextmanager
def connect(db_path: str | Path = DEFAULT_DB_PATH):
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


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
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
    if "id" in columns:
        return

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

        INSERT INTO assignments (client_id, slot_key, locked, updated_at)
        SELECT client_id, slot_key, locked, updated_at
        FROM assignments_legacy;

        DROP TABLE assignments_legacy;
        """
    )


def _migrate_proposal_assignments(conn: sqlite3.Connection) -> None:
    info = list(conn.execute("PRAGMA table_info(proposal_assignments)"))
    columns = {row["name"] for row in info}
    new_slot_is_nullable = any(
        row["name"] == "new_slot_key" and row["notnull"] == 0 for row in info
    )
    if "session_index" in columns and new_slot_is_nullable:
        return

    conn.execute("ALTER TABLE proposal_assignments RENAME TO proposal_assignments_legacy")
    conn.executescript(
        """
        CREATE TABLE proposal_assignments (
            proposal_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            old_slot_key TEXT,
            new_slot_key TEXT,
            preference_level TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL
                CHECK (change_type IN ('added', 'moved', 'unchanged', 'removed')),
            PRIMARY KEY (proposal_id, client_id, session_index),
            FOREIGN KEY (proposal_id) REFERENCES proposals(id) ON DELETE CASCADE,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        );

        INSERT INTO proposal_assignments
            (proposal_id, client_id, session_index, old_slot_key, new_slot_key,
             preference_level, change_type)
        SELECT proposal_id, client_id, 1, old_slot_key, new_slot_key,
               preference_level, change_type
        FROM proposal_assignments_legacy;

        DROP TABLE proposal_assignments_legacy;
        """
    )


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                new_client_id INTEGER,
                target_client_id INTEGER,
                proposal_type TEXT NOT NULL DEFAULT 'add',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                free_evenings INTEGER NOT NULL,
                moved_count INTEGER NOT NULL,
                proposed_name TEXT,
                proposed_location TEXT,
                proposed_notes TEXT,
                proposed_sessions_per_week INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_at TEXT,
                FOREIGN KEY (new_client_id) REFERENCES clients(id) ON DELETE SET NULL,
                FOREIGN KEY (target_client_id) REFERENCES clients(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS proposal_assignments (
                proposal_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                session_index INTEGER NOT NULL,
                old_slot_key TEXT,
                new_slot_key TEXT,
                preference_level TEXT NOT NULL DEFAULT '',
                change_type TEXT NOT NULL
                    CHECK (change_type IN ('added', 'moved', 'unchanged', 'removed')),
                PRIMARY KEY (proposal_id, client_id, session_index),
                FOREIGN KEY (proposal_id) REFERENCES proposals(id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS proposal_client_availability (
                proposal_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                preference_level TEXT NOT NULL
                    CHECK (preference_level IN ('optimal', 'secondary')),
                PRIMARY KEY (proposal_id, slot_key),
                FOREIGN KEY (proposal_id) REFERENCES proposals(id) ON DELETE CASCADE
            );
            """
        )

        # Upgrade databases created by the original one-session version.
        _add_column_if_missing(
            conn, "clients", "sessions_per_week", "INTEGER NOT NULL DEFAULT 1"
        )
        _migrate_assignments(conn)

        _add_column_if_missing(conn, "proposals", "target_client_id", "INTEGER")
        _add_column_if_missing(
            conn, "proposals", "proposal_type", "TEXT NOT NULL DEFAULT 'add'"
        )
        _add_column_if_missing(conn, "proposals", "proposed_name", "TEXT")
        _add_column_if_missing(conn, "proposals", "proposed_location", "TEXT")
        _add_column_if_missing(conn, "proposals", "proposed_notes", "TEXT")
        _add_column_if_missing(
            conn, "proposals", "proposed_sessions_per_week", "INTEGER"
        )
        conn.execute(
            """
            UPDATE proposals
            SET target_client_id = COALESCE(target_client_id, new_client_id)
            WHERE target_client_id IS NULL
            """
        )
        _migrate_proposal_assignments(conn)


def validate_client_schedule_options(
    availability: dict[str, str],
    sessions_per_week: int,
) -> None:
    from constants import SLOT_BY_KEY

    if not 1 <= sessions_per_week <= 5:
        raise ValueError("Sessions per week must be between 1 and 5.")
    if not availability:
        raise ValueError("Select at least one optimal or secondary time.")

    available_days = {SLOT_BY_KEY[slot_key].day for slot_key in availability}
    if sessions_per_week > len(available_days):
        raise ValueError(
            f"This client needs {sessions_per_week} sessions, but is only "
            f"available on {len(available_days)} different day(s)."
        )


def add_client(
    name: str,
    location: str,
    notes: str,
    availability: dict[str, str],
    sessions_per_week: int = 1,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Client name is required.")
    validate_client_schedule_options(availability, sessions_per_week)

    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO clients (name, location, notes, sessions_per_week)
            VALUES (?, ?, ?, ?)
            """,
            (cleaned_name, location.strip(), notes.strip(), sessions_per_week),
        )
        client_id = int(cursor.lastrowid)
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
        return client_id


def list_clients(
    active_only: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    query = "SELECT * FROM clients"
    params: tuple = ()
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name COLLATE NOCASE"

    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_client(client_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return dict(row) if row else None


def get_client_availability(
    client_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, str]:
    with connect(db_path) as conn:
        return {
            row["slot_key"]: row["preference_level"]
            for row in conn.execute(
                """
                SELECT slot_key, preference_level
                FROM client_availability
                WHERE client_id = ?
                """,
                (client_id,),
            )
        }


def get_all_availability(
    active_only: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[int, dict[str, str]]:
    query = """
        SELECT a.client_id, a.slot_key, a.preference_level
        FROM client_availability a
        JOIN clients c ON c.id = a.client_id
    """
    if active_only:
        query += " WHERE c.active = 1"

    result: dict[int, dict[str, str]] = {}
    with connect(db_path) as conn:
        for row in conn.execute(query):
            result.setdefault(row["client_id"], {})[row["slot_key"]] = row[
                "preference_level"
            ]
    return result


def get_current_assignments(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[int, list[dict]]:
    query = """
        SELECT a.id, a.client_id, a.slot_key, a.locked, c.name
        FROM assignments a
        JOIN clients c ON c.id = a.client_id
        WHERE c.active = 1
        ORDER BY c.name COLLATE NOCASE, a.slot_key
    """
    result: dict[int, list[dict]] = {}
    with connect(db_path) as conn:
        for row in conn.execute(query):
            result.setdefault(row["client_id"], []).append(
                {
                    "assignment_id": row["id"],
                    "slot_key": row["slot_key"],
                    "locked": bool(row["locked"]),
                    "name": row["name"],
                }
            )
    return result


def set_assignment_lock(
    client_id: int,
    slot_key: str,
    locked: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE assignments
            SET locked = ?, updated_at = CURRENT_TIMESTAMP
            WHERE client_id = ? AND slot_key = ?
            """,
            (1 if locked else 0, client_id, slot_key),
        )


def delete_client(client_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE proposals
            SET status = 'rejected', decided_at = CURRENT_TIMESTAMP
            WHERE status = 'pending'
            """
        )
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))


def _schedule_change_rows(
    proposal_id: int,
    proposed_schedule: dict[int, list[str]],
    preferences: dict[tuple[int, str], str],
    current_schedule: dict[int, list[dict]],
) -> list[tuple]:
    rows: list[tuple] = []
    all_client_ids = set(proposed_schedule) | set(current_schedule)

    for client_id in sorted(all_client_ids):
        old_slots = {
            assignment["slot_key"] for assignment in current_schedule.get(client_id, [])
        }
        new_slots = set(proposed_schedule.get(client_id, []))

        unchanged = sorted(old_slots & new_slots)
        old_remaining = sorted(old_slots - new_slots)
        new_remaining = sorted(new_slots - old_slots)
        session_index = 1

        for slot_key in unchanged:
            rows.append(
                (
                    proposal_id,
                    client_id,
                    session_index,
                    slot_key,
                    slot_key,
                    preferences.get((client_id, slot_key), "current"),
                    "unchanged",
                )
            )
            session_index += 1

        pair_count = min(len(old_remaining), len(new_remaining))
        for index in range(pair_count):
            new_slot = new_remaining[index]
            rows.append(
                (
                    proposal_id,
                    client_id,
                    session_index,
                    old_remaining[index],
                    new_slot,
                    preferences.get((client_id, new_slot), ""),
                    "moved",
                )
            )
            session_index += 1

        for new_slot in new_remaining[pair_count:]:
            rows.append(
                (
                    proposal_id,
                    client_id,
                    session_index,
                    None,
                    new_slot,
                    preferences.get((client_id, new_slot), ""),
                    "added",
                )
            )
            session_index += 1

        for old_slot in old_remaining[pair_count:]:
            rows.append(
                (
                    proposal_id,
                    client_id,
                    session_index,
                    old_slot,
                    None,
                    "",
                    "removed",
                )
            )
            session_index += 1

    return rows


def create_proposal(
    *,
    target_client_id: int,
    proposal_type: str,
    category: str,
    message: str,
    free_evenings: int,
    moved_count: int,
    proposed_schedule: dict[int, list[str]],
    preferences: dict[tuple[int, str], str],
    current_schedule: dict[int, list[dict]],
    proposed_name: str,
    proposed_location: str,
    proposed_notes: str,
    proposed_sessions_per_week: int,
    proposed_availability: dict[str, str],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    if proposal_type not in {"add", "edit"}:
        raise ValueError("Proposal type must be 'add' or 'edit'.")

    with connect(db_path) as conn:
        # A proposal is based on the current approved schedule. Keep only the
        # newest pending proposal actionable so a stale proposal cannot later
        # overwrite a newer schedule.
        conn.execute(
            """
            UPDATE proposals
            SET status = 'rejected', decided_at = CURRENT_TIMESTAMP
            WHERE status = 'pending'
            """
        )

        cursor = conn.execute(
            """
            INSERT INTO proposals
                (new_client_id, target_client_id, proposal_type, category, message,
                 free_evenings, moved_count, proposed_name, proposed_location,
                 proposed_notes, proposed_sessions_per_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_client_id if proposal_type == "add" else None,
                target_client_id,
                proposal_type,
                category,
                message,
                free_evenings,
                moved_count,
                proposed_name.strip(),
                proposed_location.strip(),
                proposed_notes.strip(),
                proposed_sessions_per_week,
            ),
        )
        proposal_id = int(cursor.lastrowid)

        rows = _schedule_change_rows(
            proposal_id,
            proposed_schedule,
            preferences,
            current_schedule,
        )
        conn.executemany(
            """
            INSERT INTO proposal_assignments
                (proposal_id, client_id, session_index, old_slot_key, new_slot_key,
                 preference_level, change_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.executemany(
            """
            INSERT INTO proposal_client_availability
                (proposal_id, slot_key, preference_level)
            VALUES (?, ?, ?)
            """,
            [
                (proposal_id, slot_key, preference)
                for slot_key, preference in proposed_availability.items()
            ],
        )
        return proposal_id


def list_proposals(
    status: str | None = "pending",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    query = "SELECT * FROM proposals"
    params: tuple = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY id DESC"

    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_proposal_assignments(
    proposal_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    query = """
        SELECT
            pa.*,
            CASE
                WHEN pa.client_id = p.target_client_id
                     AND p.proposed_name IS NOT NULL
                THEN p.proposed_name
                ELSE c.name
            END AS name
        FROM proposal_assignments pa
        JOIN clients c ON c.id = pa.client_id
        JOIN proposals p ON p.id = pa.proposal_id
        WHERE pa.proposal_id = ?
        ORDER BY
            CASE pa.change_type
                WHEN 'added' THEN 1
                WHEN 'moved' THEN 2
                WHEN 'removed' THEN 3
                ELSE 4
            END,
            c.name COLLATE NOCASE,
            pa.session_index
    """
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, (proposal_id,)).fetchall()]


def approve_proposal(proposal_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        proposal = conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if proposal is None:
            raise ValueError("Proposal not found.")
        if proposal["status"] != "pending":
            raise ValueError("Only pending proposals can be approved.")

        target_client_id = proposal["target_client_id"] or proposal["new_client_id"]
        if target_client_id is None:
            raise ValueError("The proposal's client no longer exists.")

        if proposal["proposed_name"] is not None:
            conn.execute(
                """
                UPDATE clients
                SET name = ?, location = ?, notes = ?, sessions_per_week = ?
                WHERE id = ?
                """,
                (
                    proposal["proposed_name"],
                    proposal["proposed_location"] or "",
                    proposal["proposed_notes"] or "",
                    proposal["proposed_sessions_per_week"] or 1,
                    target_client_id,
                ),
            )
            conn.execute(
                "DELETE FROM client_availability WHERE client_id = ?",
                (target_client_id,),
            )
            availability_rows = conn.execute(
                """
                SELECT slot_key, preference_level
                FROM proposal_client_availability
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchall()
            conn.executemany(
                """
                INSERT INTO client_availability
                    (client_id, slot_key, preference_level)
                VALUES (?, ?, ?)
                """,
                [
                    (target_client_id, row["slot_key"], row["preference_level"])
                    for row in availability_rows
                ],
            )

        existing_locks = {
            (row["client_id"], row["slot_key"]): row["locked"]
            for row in conn.execute(
                "SELECT client_id, slot_key, locked FROM assignments"
            )
        }
        rows = conn.execute(
            """
            SELECT client_id, new_slot_key
            FROM proposal_assignments
            WHERE proposal_id = ? AND new_slot_key IS NOT NULL
            """,
            (proposal_id,),
        ).fetchall()

        conn.execute("DELETE FROM assignments")
        conn.executemany(
            """
            INSERT INTO assignments (client_id, slot_key, locked)
            VALUES (?, ?, ?)
            """,
            [
                (
                    row["client_id"],
                    row["new_slot_key"],
                    existing_locks.get(
                        (row["client_id"], row["new_slot_key"]), 0
                    ),
                )
                for row in rows
            ],
        )
        conn.execute(
            """
            UPDATE proposals
            SET status = 'approved', decided_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (proposal_id,),
        )


def reject_proposal(proposal_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE proposals
            SET status = 'rejected', decided_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
            """,
            (proposal_id,),
        )
