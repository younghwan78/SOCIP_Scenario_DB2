from __future__ import annotations

import json
from pathlib import Path

import yaml

from scenario_db.projection.cli import main
from scenario_db.projection.verify import compute_projection_error
from scenario_db.models.evidence.simulation import SimulationEvidence

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "demo" / "projection"
RECIPE = DEMO / "uhd30-vdis-u-to-v.yaml"


def test_compute_projection_error():
    projected = {
        "kpi": {"total_power_mw": 3300.0},
        "vdd_power": {"VDD_CPU": {"mean_mw": 1650.0}},
    }
    v_meas = {
        "kpi": {"total_power_mw": {"mean": 3000.0, "n": 5}},
        "vdd_power": {"VDD_CPU": {"mean_mw": 1500.0}},
    }
    report = compute_projection_error(projected, v_meas)
    # 3300 vs 3000 -> +10%
    assert report["kpi"]["total_power_mw"]["pct_error"] == 10.0
    assert report["vdd_power"]["VDD_CPU"]["pct_error"] == 10.0
    assert report["summary"]["n"] == 2
    assert report["summary"]["mean_abs_pct_error"] == 10.0


def test_compute_projection_error_empty_overlap():
    report = compute_projection_error({"kpi": {"a": 1}}, {"kpi": {"b": 2}})
    assert report["summary"] == {"n": 0}


def test_cli_end_to_end(tmp_path: Path):
    out = tmp_path / "generated"
    rc = main(["--recipe", str(RECIPE), "--out", str(out), "--strict", "--fail-on-warning"])
    assert rc == 0

    evidence_path = out / "03_evidence" / "sim-uc-camera-recording-v-cam-rec-uhd30-vdis-PRE-SI-projection.yaml"
    assert evidence_path.exists()
    doc = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))

    SimulationEvidence.model_validate(doc)
    assert doc["execution_context"]["method"] == "projection"
    assert doc["project_ref"] == "proj-v-nextgen"
    # demo calibration factor 1.1: 3000 -> 3300
    assert doc["kpi"]["total_power_mw"] == 3300.0
    assert doc["vdd_power"]["VDD_CPU"]["mean_mw"] == 1650.0
    assert doc["ip_breakdown"][0]["power_mW"] == 880.0
    # SW timing from U scaled by BIG time_scale 0.8: 8.0 -> 6.4
    eis = next(t for t in doc["sw_task_timing"] if t["task"] == "eis_warp")
    assert eis["mean_ms"] == 6.4
    # MID time_scale 0.85: hal_request_thread 2.0 -> 1.7
    hal = next(t for t in doc["sw_task_timing"] if t["task"] == "hal_request_thread")
    assert hal["mean_ms"] == 1.7
    # lineage
    assert len(doc["derived_from"]) == 3

    report = json.loads((out / "projection_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    codes = {m["code"] for m in report["messages"]}
    assert "calibration_computed" in codes


def test_cli_verify_appends_error_report(tmp_path: Path):
    # craft a V measurement and verify against the projection
    v_meas = tmp_path / "v-meas.yaml"
    v_meas.write_text(
        yaml.safe_dump(
            {
                "id": "meas-uc-camera-recording-v-cam-rec-uhd30-vdis-ES1-20261201",
                "kind": "evidence.measurement",
                "kpi": {"total_power_mw": {"mean": 3200.0, "n": 5}},
                "vdd_power": {"VDD_CPU": {"mean_mw": 1600.0}},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "generated"
    rc = main(["--recipe", str(RECIPE), "--out", str(out), "--verify", str(v_meas)])
    assert rc == 0
    doc = yaml.safe_load(
        (out / "03_evidence" / "sim-uc-camera-recording-v-cam-rec-uhd30-vdis-PRE-SI-projection.yaml").read_text(encoding="utf-8")
    )
    err = doc["calculation_trace"]["projection"]["error_report"]
    # projected 3300 vs measured 3200 -> +3.125%
    assert err["kpi"]["total_power_mw"]["pct_error"] == 3.125
    assert err["summary"]["n"] == 2


def test_cli_missing_recipe(tmp_path: Path):
    rc = main(["--recipe", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "g"), "--strict"])
    assert rc == 1
