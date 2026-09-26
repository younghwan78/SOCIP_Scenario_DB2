"""Exynos2600 scenario files for tests: the live fixture plus the 2026-09-27 archive.

The fixture was reduced to the camera-recording KPI set; view/dashboard regression
tests keep exercising the archived scenarios (audio, display, 3rd-party ...) as data.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "db_fixtures_Exynos2600_S26Plus" / "02_definition"
ARCHIVE = ROOT / "authoring" / "archive" / "2026-09-27-scope-reduction"


def scenario_path(file_name: str, variant_id: str | None = None) -> Path:
    stem = Path(file_name).stem
    for path in (DEFINITION / file_name, ARCHIVE / file_name, ARCHIVE / f"{stem}.orig.yaml"):
        if not path.exists():
            continue
        if variant_id is None:
            return path
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if any(v.get("id") == variant_id for v in raw.get("variants") or []):
            return path
    raise FileNotFoundError(f"{file_name} ({variant_id}) not in fixture or archive")


def all_scenario_files() -> list[Path]:
    """Every Exynos2600 scenario document (fixture first, archived originals excluded)."""
    live = sorted(DEFINITION.glob("uc-*.yaml"))
    names = {p.name for p in live}
    return live + sorted(p for p in ARCHIVE.glob("uc-*.yaml") if p.name not in names and not p.name.endswith(".orig.yaml"))
