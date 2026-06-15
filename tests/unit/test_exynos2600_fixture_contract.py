from __future__ import annotations

from pathlib import Path

import yaml

from scenario_db.models.evidence.simulation import SimulationEvidence


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "db_fixtures_Exynos2600_S26Plus"
EVIDENCE_ROOT = FIXTURE_ROOT / "03_evidence"


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
    assert "cam-rec-r1-fhd30-vdis" in variant_ids
    assert "cam-rec-r1-uhd30-vdis" in variant_ids


def test_exynos2600_apv_recording_fixture_keeps_expected_uhd30_variant():
    apv = _read_yaml(FIXTURE_ROOT / "02_definition" / "uc-camera-recording-apv.yaml")
    variant_ids = {item["id"] for item in apv.get("variants") or []}

    assert "cam-rec-apv-uhd30-422-sdr" in variant_ids
    assert "cam-rec-apv-uhd30-444-sdr" in variant_ids


def test_exynos2600_uhd30_vdis_fixture_has_prediction_measurement_pair():
    measurement = _read_yaml(EVIDENCE_ROOT / "meas-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614.yaml")
    simulation = _read_yaml(EVIDENCE_ROOT / "sim-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614.yaml")

    assert measurement["kind"] == "evidence.measurement"
    assert simulation["kind"] == "evidence.simulation"
    assert simulation["scenario_ref"] == measurement["scenario_ref"] == "uc-camera-recording"
    assert simulation["variant_ref"] == measurement["variant_ref"] == "cam-rec-r1-uhd30-vdis"
    assert simulation["project_ref"] == measurement["project_ref"] == "proj-sm-s947b"
    assert simulation["execution_context"]["method"] == "calculation"
    assert simulation["kpi"]["total_power_mw"] == 681.0697728
    assert simulation["kpi"]["total_power_ma"] == 200.31463905882356
    assert simulation["calculation_trace"]["kpi"]["total_power_ma"]["inputs"] == {
        "total_power_mw": 681.0697728,
        "vbat": 4.0,
        "pmic_efficiency": 0.85,
    }
    SimulationEvidence.model_validate(simulation)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
