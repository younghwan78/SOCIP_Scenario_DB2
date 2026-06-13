from __future__ import annotations

import json
from pathlib import Path

import yaml

from scenario_db.legacy_import.report import ImportReport
from scenario_db.meas_import.assemble import assemble_evidence, generate_evidence_id
from scenario_db.meas_import.cli import main
from scenario_db.meas_import.meta import MeasurementImportMeta
from scenario_db.meas_import.perfetto_digest import PerfettoDigest
from scenario_db.meas_import.power_csv import PowerDigest
from scenario_db.models.evidence.measurement import MeasurementEvidence

REPO = Path(__file__).resolve().parents[3]
DEMO_META = REPO / "demo" / "measurements" / "uhd30-vdis" / "meta.yaml"


def _meta() -> MeasurementImportMeta:
    return MeasurementImportMeta.model_validate(
        {
            "project_ref": "proj-sm-s947b",
            "scenario_ref": "uc-camera-recording",
            "variant_ref": "cam-rec-r1-uhd30-vdis",
            "measured_at": "2026-06-10T15:20:00+09:00",
            "execution_context": {
                "silicon_rev": "EVT1",
                "sw_baseline_ref": "sw-vendor-v1.2.3",
                "thermal": "room",
            },
            "kpi": {"frame_latency_ms": 28.4},
            "power": {"csv": "p.csv", "rails": {}},
        }
    )


def test_generate_evidence_id():
    meta = _meta()
    assert generate_evidence_id(meta) == "meas-uc-camera-recording-cam-rec-r1-uhd30-vdis-EVT1-20260610"


def test_assemble_merges_power_and_perfetto():
    meta = _meta()
    power = PowerDigest(
        cpu_cluster_power={"BIG": {"mean": 410.0, "p95": 520.0, "std": 41.0, "n": 5}},
        vdd_power={"VDD_CAM": {"mean_mw": 980.0, "p95_mw": 1080.0}},
        total_power_mw={"mean": 3850.0, "p95": 4010.0, "std": 72.0, "n": 5},
    )
    perfetto = PerfettoDigest()
    perfetto.freq_residency = {"BIG": [{"freq_mhz": 1920.0, "ratio": 1.0, "time_ms": 1.0}]}
    perfetto.cluster_avg_freq = {"BIG": 1920.0}
    perfetto.sw_task_timing = [{"task": "eis_warp", "mean_ms": 7.8, "samples": 100}]

    report = ImportReport()
    doc = assemble_evidence(meta, power, perfetto, base_dir=Path("."), report=report)

    # power KPI + meta passthrough merged
    assert doc["kpi"]["total_power_mw"]["mean"] == 3850.0
    assert doc["kpi"]["frame_latency_ms"] == 28.4
    # cpu_breakdown fuses power + perfetto for the same cluster
    big = next(c for c in doc["cpu_breakdown"] if c["cluster"] == "BIG")
    assert big["power_mw"]["mean"] == 410.0
    assert big["avg_freq_mhz"] == 1920.0
    assert big["freq_residency"][0]["freq_mhz"] == 1920.0
    assert doc["sw_task_timing"][0]["task"] == "eis_warp"
    assert doc["vdd_power"]["VDD_CAM"]["mean_mw"] == 980.0
    assert doc["execution_context"]["method"] == "measurement"

    # the assembled doc validates against the canonical contract
    MeasurementEvidence.model_validate(doc)


def test_meta_kpi_total_power_wins_over_power_digest():
    meta = _meta()
    meta.kpi["total_power_mw"] = 1234.0
    power = PowerDigest(total_power_mw={"mean": 3850.0, "p95": 4010.0, "n": 5})
    doc = assemble_evidence(meta, power, None, base_dir=Path("."), report=ImportReport())
    assert doc["kpi"]["total_power_mw"] == 1234.0


def test_cli_end_to_end_power_only(tmp_path: Path, capsys):
    """Demo capture has no trace file -> power-only digest with a warning."""
    out = tmp_path / "generated"
    rc = main(["--meta", str(DEMO_META), "--out", str(out)])
    assert rc == 0  # not strict, warning about missing trace is tolerated

    evidence_path = out / "03_evidence" / "meas-uc-camera-recording-cam-rec-r1-uhd30-vdis-EVT1-20260610.yaml"
    assert evidence_path.exists()
    doc = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))

    # validates against the contract
    MeasurementEvidence.model_validate(doc)
    assert doc["kind"] == "evidence.measurement"
    assert doc["project_ref"] == "proj-sm-s947b"
    assert doc["kpi"]["total_power_mw"]["n"] == 12
    assert doc["kpi"]["frame_latency_ms"] == 28.4
    clusters = {c["cluster"] for c in doc["cpu_breakdown"]}
    assert clusters == {"BIG", "MID", "LIT"}
    # power CSV present, but trace missing -> no sw_task_timing / freq_residency
    assert "sw_task_timing" not in doc
    assert all("freq_residency" not in c for c in doc["cpu_breakdown"])
    # power_monitor.csv artifact got a real sha256 (source file exists in demo dir)
    csv_art = next(a for a in doc["artifacts"] if a["type"] == "power_monitor_csv")
    assert "sha256" in csv_art and len(csv_art["sha256"]) == 64

    report = json.loads((out / "meas_import_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["generated"]["evidence_measurement"] == 1
    codes = {m["code"] for m in report["messages"]}
    assert "perfetto_trace_not_found" in codes


def test_cli_strict_fails_on_warning(tmp_path: Path):
    out = tmp_path / "generated"
    rc = main(["--meta", str(DEMO_META), "--out", str(out), "--strict", "--fail-on-warning"])
    assert rc == 1  # missing trace warning -> non-zero under --fail-on-warning


def test_cli_skip_perfetto_drops_trace_lookup(tmp_path: Path):
    """--skip-perfetto removes the trace-digest lookup; the trace *artifact*
    pointer warning remains because the raw file lives in the file store, not
    the repo."""
    out = tmp_path / "generated"
    rc = main(["--meta", str(DEMO_META), "--out", str(out), "--skip-perfetto"])
    assert rc == 0  # not strict
    report = json.loads((out / "meas_import_report.json").read_text(encoding="utf-8"))
    codes = {m["code"] for m in report["messages"]}
    assert "perfetto_trace_not_found" not in codes
    assert "perfetto_skipped" in codes


def test_cli_missing_meta(tmp_path: Path):
    rc = main(["--meta", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "g"), "--strict"])
    assert rc == 1
