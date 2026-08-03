from constants import APP_BUILD

EXPECTED_BUILD = "2026.08.03-v2"

if APP_BUILD != EXPECTED_BUILD:
    raise RuntimeError(
        "Project files are from different versions. Upload all project files together."
    )
