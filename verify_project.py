from __future__ import annotations

import ast
import py_compile
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPECTED_BUILD = "2026.08.03-v2"
REQUIRED_FILES = [
    "app.py",
    "constants.py",
    "database.py",
    "project_version.py",
    "scheduler_service.py",
    "solver.py",
    "requirements.txt",
    "README.md",
    ".gitignore",
    "scheduler.db",
    "seed_demo_database.py",
    "create_empty_database.py",
    "tests/test_solver.py",
    "tests/test_seed_database.py",
]


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(1)


for relative_name in REQUIRED_FILES:
    if not (ROOT / relative_name).is_file():
        fail(f"Missing {relative_name}")

constants_text = (ROOT / "constants.py").read_text(encoding="utf-8")
if f'APP_BUILD = "{EXPECTED_BUILD}"' not in constants_text:
    fail("constants.py is from a different build.")
if "from constants import" in constants_text or "import constants" in constants_text:
    fail("constants.py imports itself.")

solver_text = (ROOT / "solver.py").read_text(encoding="utf-8")
if "streamlit>=" in solver_text:
    fail("solver.py contains requirements.txt text.")

required_names = {
    "solver.py": {"ClientInput", "ScheduleResult", "solve_schedule"},
    "scheduler_service.py": {
        "add_client",
        "edit_client",
        "delete_client",
        "approve_draft",
        "discard_draft",
    },
}
for filename, names in required_names.items():
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    found = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    missing = sorted(names - found)
    if missing:
        fail(f"{filename} is missing: {', '.join(missing)}")

for filename in [
    "app.py",
    "constants.py",
    "database.py",
    "project_version.py",
    "scheduler_service.py",
    "solver.py",
    "seed_demo_database.py",
    "create_empty_database.py",
]:
    try:
        py_compile.compile(str(ROOT / filename), doraise=True)
    except py_compile.PyCompileError as exc:
        fail(f"{filename} does not compile: {exc.msg}")

# SQLite schema smoke test without touching the real scheduler.db.
import database

with tempfile.TemporaryDirectory() as directory:
    db_path = Path(directory) / "smoke.db"
    database.init_db(db_path)
    connection = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    connection.close()
    expected_tables = {
        "clients",
        "client_availability",
        "assignments",
        "settings",
        "draft_changes",
        "draft_assignments",
        "draft_meta",
    }
    missing_tables = expected_tables - tables
    if missing_tables:
        fail("Database setup is missing: " + ", ".join(sorted(missing_tables)))


# Verify the included ready-to-use database without changing it.
real_db = ROOT / "scheduler.db"
connection = sqlite3.connect(real_db)
connection.row_factory = sqlite3.Row
try:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        fail("scheduler.db failed SQLite integrity_check.")
    client_count = connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    appointment_count = connection.execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
    draft_count = connection.execute("SELECT COUNT(*) FROM draft_changes").fetchone()[0]
finally:
    connection.close()
if client_count < 1 or appointment_count < 1:
    fail("scheduler.db does not contain the included sample schedule.")
if draft_count != 0:
    fail("The included scheduler.db should not contain pending draft changes.")

print("Project files match and compile correctly.")
print(f"Build: {EXPECTED_BUILD}")
print(f"Included database: {client_count} sample clients, {appointment_count} appointments")
print("Next: python -m pip install -r requirements.txt")
print("Then: python -m pytest")
print("Then: python -m streamlit run app.py")
