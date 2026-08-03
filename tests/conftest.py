from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for path in (str(ROOT), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from ortools.sat.python import cp_model as _real_cp_model  # noqa: F401
except ImportError:
    import fake_cp_model as cp_model

    ortools = types.ModuleType("ortools")
    sat = types.ModuleType("ortools.sat")
    python_pkg = types.ModuleType("ortools.sat.python")
    python_pkg.cp_model = cp_model
    sys.modules["ortools"] = ortools
    sys.modules["ortools.sat"] = sat
    sys.modules["ortools.sat.python"] = python_pkg
    sys.modules["ortools.sat.python.cp_model"] = cp_model
