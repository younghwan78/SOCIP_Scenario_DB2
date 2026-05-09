from __future__ import annotations

from pathlib import Path

import yaml


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "db_fixtures_Exynos2600_S26Plus"


def test_exynos2600_camera_recording_and_apv_scenarios_are_both_present():
    definition_dir = FIXTURE_ROOT / "02_definition"
    recording = _read_yaml(definition_dir / "uc-camera-recording.yaml")
    apv = _read_yaml(definition_dir / "uc-camera-recording-apv.yaml")

    assert recording["id"] == "uc-camera-recording"
    assert recording["project_ref"] == "proj-sm-s947b"
    assert recording["metadata"]["name"] == "Camera Recording"
    assert apv["id"] == "uc-camera-recording-apv"
    assert apv["project_ref"] == "proj-sm-s947b"
    assert apv["metadata"]["name"] == "Camera Recording APV"


def test_exynos2600_recording_fixture_keeps_expected_fhd30_variant():
    recording = _read_yaml(FIXTURE_ROOT / "02_definition" / "uc-camera-recording.yaml")
    variant_ids = {item["id"] for item in recording.get("variants") or []}

    assert "cam-rec-f1-fhd30" in variant_ids
    assert "cam-rec-f1-fhd30-recursive" in variant_ids


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
