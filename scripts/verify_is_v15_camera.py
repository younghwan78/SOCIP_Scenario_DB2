"""Verify IS v15 recording and explore a bounded, explicitly assumed clock grid.

Run from implementation/: .venv/Scripts/python.exe scripts/verify_is_v15_camera.py
Add --write-evidence to materialize the selected configurations and estimated evidence.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import json

import networkx as nx
import yaml

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.db.repositories.variant_resolution import resolve_variant_from_rows
from scenario_db.models.definition.usecase import Usecase
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "db_fixtures_Exynos2600_S26Plus"
SCENARIO_PATH = FIXTURE / "02_definition/uc-camera-recording.yaml"
KPI_VARIANTS = (
    "cam-rec-r1-fhd30-vdis", "cam-rec-r1-fhd60-supersteady",
    "cam-rec-r1-uhd30-vdis", "cam-rec-r1-uhd60-supersteady",
)
CLOCKS = (300, 400, 600, 800, 1000)
CAMERA_NODES = ("csis", "pdp", "byrp", "rgbp", "yuvsc", "mlsc", "mtnr", "msnr", "yuvp", "mcsc", "lme", "vps_od", "gdc_m", "gdc_o")


def read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def graph_from_fixture(raw: dict, variant_id: str, catalog: dict) -> CanonicalScenarioGraph:
    scenario = Scenario(id=raw["id"], schema_version=raw["schema_version"], project_ref=raw["project_ref"],
                        metadata_=raw["metadata"], pipeline=raw["pipeline"], size_profile=raw.get("size_profile"), yaml_sha256="fixture")
    rows = {v["id"]: ScenarioVariant(scenario_id=raw["id"], **{
        k: deepcopy(value) for k, value in v.items()
    }) for v in raw["variants"]}
    variant = resolve_variant_from_rows(rows, raw["id"], variant_id)
    return CanonicalScenarioGraph(scenario=scenario, variant=variant, ip_catalog=catalog)


def assess(result, fps: float, latency_frames: float) -> dict:
    sinks = [e for e in result.timeline_events if e.node_id in {"mfc_enc", "panel"}]
    latency = max((e.end_ms - e.frame_index * 1000 / fps for e in sinks), default=float("inf"))
    cadence = max((e.cadence_avg_interval_ms or 0 for e in sinks), default=float("inf"))
    cadence_ok = cadence <= 1000 / fps + 1e-5
    return {"accepted": result.feasible and cadence_ok and latency <= latency_frames * 1000 / fps + 1e-5,
            "max_frame_latency_ms": round(latency, 6), "average_sink_interval_ms": round(cadence, 6),
            "latency_budget_ms": latency_frames * 1000 / fps, "cadence_ok": cadence_ok}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--latency-frames", type=float, default=3.0,
                        help="Assumed end-to-end latency budget; not a measured product requirement")
    args = parser.parse_args()
    if args.latency_frames <= 0:
        parser.error("--latency-frames must be positive")
    raw = read(SCENARIO_PATH)
    Usecase.model_validate(raw)
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                    hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    report = {"assumptions": [
        "Clock grid is an engineering assumption, not the silicon DVFS table.",
        "Selection minimizes requested camera clock on the tested grid; it is not a power optimum.",
        "Sensor/RT stay synchronized; the selected clock must also satisfy sensor ingress.",
        "Eight-frame deterministic timing; min/max runtime cases keep mean start jitter at 1ms.",
        "CPU active power and uncharacterized statistic/chroma/weight traffic are excluded.",
        "History is warmed-up steady state. Actual FIFO depth, arbitration, and jitter tails are uncharacterized.",
    ], "verified_variants": [], "requires_runtime_confirmation": [], "exploration": []}
    for variant in raw["variants"]:
        graph = graph_from_fixture(raw, variant["id"], catalog)
        inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=1))
        dag = nx.DiGraph((e["from"], e["to"]) for e in inputs.timeline_edges)
        if not nx.is_directed_acyclic_graph(dag):
            raise ValueError(f"{variant['id']}: timing dependency cycle")
        for port in inputs.port_transfers:
            modules = catalog[port.ip_ref].capabilities.get("properties", {}).get("modules", [])
            if port.port not in {m["name"] for m in modules}:
                raise ValueError(f"{variant['id']}: undeclared DMA {port.node_id}.{port.port}")
        report["verified_variants"].append(variant["id"])
        conditions = graph.variant.design_conditions
        sensors = [n for n in graph.pipeline_nodes if n.get("role") == "sensor"]
        if conditions.get("sensor_support") or conditions.get("sensor_cadence_policy") or len(sensors) != 1:
            report["requires_runtime_confirmation"].append(variant["id"])
    additions = []
    for parent in KPI_VARIANTS:
        for case in ("min", "mean", "max"):
            candidates = []
            selected = None
            for clock in CLOCKS:
                graph = graph_from_fixture(raw, parent, catalog)
                graph.variant.design_conditions["sw_timing_case"] = case
                for node in CAMERA_NODES:
                    graph.variant.node_configs.setdefault(node, {}).setdefault("sim", {})["manual_clock_mhz"] = clock
                inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=8, debug_trace=True))
                result = run_simulation(inputs, dvfs_tables={})
                check = {"requested_clock_mhz": clock, **assess(result, inputs.config.fps, args.latency_frames)}
                candidates.append(check)
                if selected is None and check["accepted"]:
                    selected = (clock, inputs, result, check)
            row = {"variant": parent, "sw_timing_case": case, "candidates": candidates,
                   "selected_clock_mhz": selected[0] if selected else None}
            report["exploration"].append(row)
            if not args.write_evidence or selected is None:
                continue
            clock, inputs, result, check = selected
            variant_id = parent + "-explored-" + case
            additions.append({"id": variant_id, "severity": "medium", "derived_from_variant": parent,
                "design_conditions_override": {"sw_timing_case": case, "exploration_clock_mhz": clock,
                    "assumed_latency_budget_frames": args.latency_frames},
                "node_configs": {node: {"sim": {"manual_clock_mhz": clock}} for node in CAMERA_NODES},
                "tags": ["is-v15", "exploration-only", "assumed-clock-grid", "uncalibrated-power"]})
            inputs.variant_id = variant_id
            result.variant_id = variant_id
            result.warnings.extend(report["assumptions"])
            if result.calculation_trace is not None:
                result.calculation_trace["warnings"] = result.warnings
                result.calculation_trace["exploration"] = check
            evidence = build_simulation_evidence(result, project_ref=raw["project_ref"], params_hash=params_hash(inputs),
                evidence_id="sim-is-v15-" + variant_id.removeprefix("cam-rec-") + "-20260913",
                execution_context=ExecutionContext(silicon_rev="EVT1", sw_baseline_ref="sw-vendor-v1.2.3", thermal="room", method="calculation"),
                timestamp="2026-09-13T00:00:00+09:00")
            output = FIXTURE / "03_evidence" / (evidence.id + ".yaml")
            output.write_text(yaml.safe_dump(evidence.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True), encoding="utf-8")
    if additions:
        ids = {v["id"] for v in additions}
        raw["variants"] = [v for v in raw["variants"] if v["id"] not in ids] + additions
        Usecase.model_validate(raw)
        SCENARIO_PATH.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    out = ROOT / "output/is-v15-camera"
    out.mkdir(parents=True, exist_ok=True)
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# IS v15 camera recording verification", "", f"Validated {len(report['verified_variants'])} effective variants; {len(report['requires_runtime_confirmation'])} require runtime sensor/routing confirmation.", "", "## Assumptions", ""]
    lines += ["- " + value for value in report["assumptions"]]
    lines += ["", "## Lowest tested clock meeting the assumed latency and cadence limits", "", "| Variant | SW case | Clock MHz | Max frame latency ms |", "| --- | --- | ---: | ---: |"]
    for row in report["exploration"]:
        selected = next((c for c in row["candidates"] if c["accepted"]), None)
        lines.append(f"| {row['variant']} | {row['sw_timing_case']} | {row['selected_clock_mhz']} | {selected['max_frame_latency_ms'] if selected else 'No feasible candidate'} |")
    lines += ["", "## Runtime confirmation required", ""] + ["- " + v for v in report["requires_runtime_confirmation"]]
    (out / "verification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"variants": len(report["verified_variants"]), "runtime_confirmation": len(report["requires_runtime_confirmation"]),
                      "exploration": [{k: v for k, v in row.items() if k != "candidates"} for row in report["exploration"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
