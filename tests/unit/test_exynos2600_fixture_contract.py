from __future__ import annotations

from pathlib import Path

import yaml

from scenario_db.models.evidence.simulation import SimulationEvidence


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "db_fixtures_Exynos2600_S26Plus"
EVIDENCE_ROOT = FIXTURE_ROOT / "03_evidence"


KPI_SET = {
    "cam-rec-r1-fhd30-vdis", "cam-rec-r1-fhd60-supersteady", "cam-rec-r1-uhd30-vdis", "cam-rec-r1-uhd60-psm",
    "cam-rec-r1-8k30-psm", "cam-rec-r1-fhd120", "cam-rec-r1-fhd240", "cam-rec-r1-uhd120",
    "cam-rec-r1-uhd30-pro", "cam-rec-r1-uhd60-pro", "cam-rec-r1-uhd120-pro",
    "cam-rec-r1-fhd30-portrait", "cam-rec-r1-uhd30-portrait", "cam-rec-pip-fhd30", "cam-rec-pip-uhd30",
    "cam-rec-apv-uhd30-422-sdr", "cam-rec-apv-uhd60-422-sdr", "cam-rec-apv-uhd120-422-sdr",
}


def test_exynos2600_fixture_is_the_camera_recording_kpi_set():
    definition_dir = FIXTURE_ROOT / "02_definition"
    assert sorted(p.name for p in definition_dir.glob("*.yaml")) == ["proj-sm-s947b.yaml", "uc-cam-recording-e2600.yaml"]
    recording = _read_yaml(definition_dir / "uc-cam-recording-e2600.yaml")
    assert recording["project_ref"] == "proj-sm-s947b"
    assert recording["metadata"]["canonical_usecase"] == "uc-cam-recording"
    assert {v["id"] for v in recording["variants"]} == KPI_SET


def test_exynos2600_evidence_only_references_kpi_variants():
    for path in EVIDENCE_ROOT.glob("*.yaml"):
        doc = _read_yaml(path)
        assert doc["scenario_ref"] == "uc-cam-recording-e2600", path.name
        assert doc["variant_ref"] in KPI_SET, path.name


def test_exynos2600_uhd30_vdis_fixture_has_prediction_measurement_pair():
    measurement = _read_yaml(EVIDENCE_ROOT / "meas-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614.yaml")
    simulation = _read_yaml(EVIDENCE_ROOT / "sim-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614.yaml")

    assert measurement["kind"] == "evidence.measurement"
    assert simulation["kind"] == "evidence.simulation"
    assert simulation["scenario_ref"] == measurement["scenario_ref"] == "uc-cam-recording-e2600"
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
