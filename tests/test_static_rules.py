from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_user_facing_words_are_updated() -> None:
    app_text = (ROOT / "app.py").read_text(encoding="utf-8").lower()
    service_text = (ROOT / "scheduler_service.py").read_text(encoding="utf-8").lower()
    combined = app_text + service_text
    assert "deactivate" not in combined
    assert "works excellent" not in combined
    assert "cannot fit" not in combined
    assert "best time" in combined
    assert "also works" in combined
    assert "draft schedule" in combined


def test_all_pages_exist() -> None:
    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    for page in ["Schedule", "Add Client", "Clients", "Review Changes", "Settings"]:
        assert page in app_text
