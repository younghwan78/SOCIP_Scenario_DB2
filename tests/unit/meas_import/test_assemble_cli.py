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
PATH_A_META = REPO / "examples" / "measurement-import" / "path-a-capture" / "meta.yaml"
PATH_B_CANONICAL = REPO / "examples" / "measurement-import" / "path-b-canonical" / "meas-example-canonical.yaml"
EXYNOS2600_MEAS_FIXTURE = (
    REPO
    / "db_fixtures_Exynos2600_S26Plus"
    / "03_evidence"
    / "meas-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614.yaml"
)


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
    assert generate_evidence_id(meta) == "meas-proj-sm-s947b-uc-camera-recording-cam-rec-r1-uhd30-vdis-EVT1-20260610T152000"


def test_assemble_merges_power_and_perfetto():
    meta = _meta()
    power = PowerDigest(
        rail_kpi={"VDD_CAM": {"mean": 980.0, "p95": 1080.0, "std": 20.0, "n": 5}},
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
    observations = {
        (item["metric_id"], item["scope"]["kind"], item["scope"]["ref"]): item
        for item in doc["metric_observations"]
    }
    assert observations[("power.total", "scenario", "self")]["stats"]["mean"] == 3850.0
    assert observations[("latency.frame", "scenario", "self")]["value"] == 28.4
    assert observations[("power.rail", "rail", "VDD_CAM")]["stats"]["p95"] == 1080.0
    assert observations[("sw.runtime", "task", "eis_warp")]["stats"]["mean"] == 7.8

    # the assembled doc validates against the canonical contract
    MeasurementEvidence.model_validate(doc)


def test_meta_kpi_total_power_wins_over_power_digest():
    meta = _meta()
    meta.kpi["total_power_mw"] = 1234.0
    power = PowerDigest(total_power_mw={"mean": 3850.0, "p95": 4010.0, "n": 5})
    doc = assemble_evidence(meta, power, None, base_dir=Path("."), report=ImportReport())
    assert doc["kpi"]["total_power_mw"] == 1234.0
    total = next(
        item for item in doc["metric_observations"] if item["metric_id"] == "power.total"
    )
    assert total["value"] == 1234.0


def test_malformed_kpi_dict_is_skipped_not_crashed():
    """A dict KPI with no recognizable stat keys (e.g. {avg: ...}) must not
    become an invalid observation that explodes as a raw ValidationError."""
    meta = _meta()
    meta.kpi["total_power_mw"] = {"avg": 100.0}
    doc = assemble_evidence(meta, None, None, base_dir=Path("."), report=ImportReport())
    ids = {item["metric_id"] for item in doc.get("metric_observations", [])}
    assert "power.total" not in ids
    # the well-formed scalar KPI still produces its observation
    assert "latency.frame" in ids


def test_explicit_observation_wins_over_derived_digest():
    raw = _meta().model_dump(mode="json", exclude_none=True)
    raw["metric_observations"] = [
        {
            "metric_id": "power.rail",
            "scope": {"kind": "rail", "ref": "VDD_CAM"},
            "unit": "mW",
            "value": 999.0,
        }
    ]
    meta = MeasurementImportMeta.model_validate(raw)
    power = PowerDigest(
        rail_kpi={"VDD_CAM": {"mean": 100.0, "p95": 120.0, "n": 2}},
        vdd_power={"VDD_CAM": {"mean_mw": 100.0, "p95_mw": 120.0}},
        sample_count=2,
    )

    doc = assemble_evidence(meta, power, None, base_dir=Path("."), report=ImportReport())
    matching = [
        item
        for item in doc["metric_observations"]
        if item["metric_id"] == "power.rail" and item["scope"]["ref"] == "VDD_CAM"
    ]

    assert matching == [
        {
            "metric_id": "power.rail",
            "scope": {"kind": "rail", "ref": "VDD_CAM"},
            "unit": "mW",
            "value": 999.0,
        }
    ]


def test_cli_accepts_observation_only_canonical_yaml(tmp_path: Path):
    meta_path = tmp_path / "meta.yaml"
    meta_path.write_text(
        """
project_ref: proj-sm-s947b
scenario_ref: uc-camera-recording
variant_ref: cam-rec-r1-uhd30-vdis
measured_at: "2026-06-10T15:20:00+09:00"
execution_context:
  silicon_rev: EVT1
  sw_baseline_ref: sw-vendor-v1.2.3
  thermal: room
metric_observations:
  - metric_id: sw.start_jitter
    scope: {kind: task, ref: eis_warp}
    unit: us
    stats: {mean: 84, p95: 210, n: 5400}
""".strip(),
        encoding="utf-8",
    )
    out = tmp_path / "generated"

    rc = main(["--meta", str(meta_path), "--out", str(out), "--strict"])

    assert rc == 0
    evidence_path = next((out / "03_evidence").glob("*.yaml"))
    doc = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    assert doc["metric_observations"][0]["metric_id"] == "sw.start_jitter"


def test_cli_accepts_kpi_only_canonical_yaml(tmp_path: Path):
    meta_path = tmp_path / "meta.yaml"
    meta_path.write_text(
        """
project_ref: proj-sm-s947b
scenario_ref: uc-camera-recording
variant_ref: cam-rec-r1-uhd30-vdis
measured_at: "2026-06-10T15:20:00+09:00"
execution_context:
  silicon_rev: EVT1
  sw_baseline_ref: sw-vendor-v1.2.3
  thermal: room
kpi:
  total_bw_mbs: {mean: 6225, p95: 6410, n: 10}
  frame_latency_ms: {mean: 28.4, p95: 32.1, n: 5400}
""".strip(),
        encoding="utf-8",
    )
    out = tmp_path / "generated"

    rc = main(["--meta", str(meta_path), "--out", str(out), "--strict"])

    assert rc == 0
    evidence_path = next((out / "03_evidence").glob("*.yaml"))
    doc = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    observations = {item["metric_id"]: item for item in doc["metric_observations"]}
    assert observations["bandwidth.total"]["stats"]["p95"] == 6410.0
    assert observations["latency.frame"]["stats"]["p95"] == 32.1


def test_cli_end_to_end_power_only(tmp_path: Path, capsys):
    """Demo capture has no trace file -> power-only digest with a warning."""
    out = tmp_path / "generated"
    rc = main(["--meta", str(DEMO_META), "--out", str(out)])
    assert rc == 0  # not strict, warning about missing trace is tolerated

    evidence_path = out / "03_evidence" / "meas-proj-sm-s947b-uc-camera-recording-cam-rec-r1-uhd30-vdis-EVT1-20260610T152000.yaml"
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


def test_path_b_power_digest_matches_path_a_generated_output(tmp_path: Path):
    out = tmp_path / "generated"
    rc = main(["--meta", str(PATH_A_META), "--out", str(out), "--strict"])
    assert rc == 0

    path_a = yaml.safe_load((out / "03_evidence" / "meas-example-patha-uhd30-vdis-20260614.yaml").read_text(encoding="utf-8"))
    path_b = yaml.safe_load(PATH_B_CANONICAL.read_text(encoding="utf-8"))

    assert path_b["kpi"]["total_power_mw"] == path_a["kpi"]["total_power_mw"]
    assert path_b["vdd_power"] == path_a["vdd_power"]
    assert {
        row["cluster"]: row["power_mw"]
        for row in path_b["cpu_breakdown"]
    } == {
        row["cluster"]: row["power_mw"]
        for row in path_a["cpu_breakdown"]
    }


def test_exynos2600_fixture_power_digest_matches_path_a_generated_output(tmp_path: Path):
    out = tmp_path / "generated"
    rc = main(["--meta", str(PATH_A_META), "--out", str(out), "--strict"])
    assert rc == 0

    path_a = yaml.safe_load((out / "03_evidence" / "meas-example-patha-uhd30-vdis-20260614.yaml").read_text(encoding="utf-8"))
    fixture = yaml.safe_load(EXYNOS2600_MEAS_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["kpi"]["total_power_mw"] == path_a["kpi"]["total_power_mw"]
    assert fixture["vdd_power"] == path_a["vdd_power"]
    assert {
        row["cluster"]: row["power_mw"]
        for row in fixture["cpu_breakdown"]
    } == {
        row["cluster"]: row["power_mw"]
        for row in path_a["cpu_breakdown"]
    }


def test_cli_missing_meta(tmp_path: Path):
    rc = main(["--meta", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "g"), "--strict"])
    assert rc == 1
