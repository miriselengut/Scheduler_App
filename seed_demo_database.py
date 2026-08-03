from __future__ import annotations

import argparse
from pathlib import Path

import database

DB_PATH = Path(__file__).with_name("scheduler.db")


DEMO_CLIENTS = [
    {
        "name": "Eli Rosen",
        "location": "Main Office",
        "notes": "Bring the reading folder.",
        "sessions_per_week": 1,
        "availability": {
            "SUN_1400": "optimal",
            "SUN_1430": "optimal",
            "MON_1400": "secondary",
            "TUE_1400": "secondary",
        },
        "assignments": [("SUN_1400", 0)],
    },
    {
        "name": "Ari Levy",
        "location": "Main Office",
        "notes": "Focus: organization and homework planning.",
        "sessions_per_week": 1,
        "availability": {
            "SUN_1430": "optimal",
            "SUN_1500": "optimal",
            "MON_1430": "secondary",
        },
        "assignments": [("SUN_1430", 0)],
    },
    {
        "name": "Miriam Cohen",
        "location": "North Campus",
        "notes": "Two sessions each week, on different days.",
        "sessions_per_week": 2,
        "availability": {
            "MON_1400": "optimal",
            "MON_1430": "optimal",
            "TUE_1400": "optimal",
            "TUE_1430": "optimal",
            "SUN_1500": "secondary",
            "WED_1400": "secondary",
        },
        "assignments": [("MON_1400", 0), ("TUE_1400", 0)],
    },
    {
        "name": "Leah Gold",
        "location": "Zoom",
        "notes": "Virtual session. Send the link before the appointment.",
        "sessions_per_week": 1,
        "availability": {
            "MON_1430": "optimal",
            "MON_1500": "optimal",
            "TUE_1430": "secondary",
        },
        "assignments": [("MON_1430", 0)],
    },
    {
        "name": "Noa Klein",
        "location": "South Campus",
        "notes": "Parent prefers afternoon appointments.",
        "sessions_per_week": 1,
        "availability": {
            "TUE_1430": "optimal",
            "TUE_1500": "optimal",
            "SUN_1500": "secondary",
        },
        "assignments": [("TUE_1430", 0)],
    },
    {
        "name": "Yael Stein",
        "location": "Main Office",
        "notes": "This sample appointment is locked.",
        "sessions_per_week": 1,
        "availability": {
            "TUE_1500": "optimal",
            "TUE_1530": "optimal",
            "SUN_1500": "secondary",
        },
        "assignments": [("TUE_1500", 1)],
    },
    {
        "name": "David Katz",
        "location": "Zoom",
        "notes": "Evening appointment.",
        "sessions_per_week": 1,
        "availability": {
            "SUN_2000": "optimal",
            "SUN_2030": "optimal",
            "MON_2000": "secondary",
        },
        "assignments": [("SUN_2000", 0)],
    },
    {
        "name": "Sara Weiss",
        "location": "Main Office",
        "notes": "Evening appointment.",
        "sessions_per_week": 1,
        "availability": {
            "MON_2000": "optimal",
            "MON_2030": "optimal",
            "TUE_2000": "secondary",
        },
        "assignments": [("MON_2000", 0)],
    },
]


def seed_demo_database(db_path: Path = DB_PATH, *, overwrite: bool = False) -> None:
    if db_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"{db_path.name} already exists. Run with --force only when you want "
                "to replace all current data with the examples."
            )
        db_path.unlink()

    database.init_db(db_path)
    assignment_rows: list[tuple[int, str, int]] = []
    active_ids: list[int] = []

    for client in DEMO_CLIENTS:
        client_id = database.create_waiting_client(
            name=client["name"],
            location=client["location"],
            notes=client["notes"],
            sessions_per_week=client["sessions_per_week"],
            availability=client["availability"],
            db_path=db_path,
        )
        active_ids.append(client_id)
        assignment_rows.extend(
            (client_id, slot_key, locked)
            for slot_key, locked in client["assignments"]
        )

    database.replace_approved_schedule(
        assignment_rows,
        active_client_ids=active_ids,
        db_path=db_path,
    )
    database.set_preferred_evenings("Wednesday", "Thursday", db_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replace scheduler.db with the included sample clients and schedule."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing scheduler.db. This permanently erases its current data.",
    )
    args = parser.parse_args()
    seed_demo_database(overwrite=args.force)
    print(f"Created demo database: {DB_PATH}")
    print(f"Clients: {len(DEMO_CLIENTS)}")
