from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import database

DB_PATH = Path(__file__).with_name("scheduler.db")


def create_empty_database(*, force: bool = False) -> None:
    if DB_PATH.exists():
        if not force:
            raise FileExistsError(
                "scheduler.db already exists. Run with --force only when you are ready "
                "to replace it with a blank database."
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DB_PATH.with_name(f"scheduler_backup_{timestamp}.db")
        DB_PATH.replace(backup)
        print(f"Backup created: {backup.name}")

    database.init_db(DB_PATH)
    print(f"Created empty database: {DB_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Back up scheduler.db and create a new empty scheduler database."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Back up and replace an existing scheduler.db.",
    )
    args = parser.parse_args()
    create_empty_database(force=args.force)
