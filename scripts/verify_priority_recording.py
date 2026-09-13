"""Explore priority recording cases with explicit sink/cadence and uncertainty checks."""
from copy import deepcopy
import argparse
import json

import networkx as nx
import yaml

from verify_is_v15_camera import FIXTURE, CLOCKS, graph_from_fixture, read
from enrich_priority_recording import PRIORITY, sync_import_bundle
from scenario_db.db.models.capability import IpCatalog
from scenario_db.models.definition.usecase import Usecase
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation


def assess_priority(graph, inputs, result):
    fps = inputs.config.fps
    sink_ids = {"storage_write", "panel"}
    events = [e for e in result.timeline_events if e.node_id in sink_ids]
    observed = {e.node_id for e in events}
    latency = max((e.end_ms - e.frame_index * 1000 / fps for e in events), default=0)
    cadence = max((e.cadence_avg_interval_ms or 0 for e in events), default=0)
    sensor_fps = [d.get("fps") for d in inputs.external_devices if d.get("device_type") == "sensor"]
    # Explicit user FHD240/120 input mismatch must not pass via a clock change.
    declared = (graph.variant.design_conditions or {}).get("sensor_input_fps")
    mismatch = bool(declared and abs(float(declared) - fps) > .01) or any(value and abs(float(value) - fps) > .01 for value in sensor_fps)
    reasons = []
    if observed != sink_ids:
        reasons.append("missing_output_sink")
    if mismatch:
        reasons.append("sensor_output_cadence_mismatch")
    if cadence > 1000/fps + 1e-5:
        reasons.append("output_cadence_miss")
    if latency > 3*1000/fps + 1e-5:
        reasons.append("three_frame_latency_budget_miss")
    if not result.feasible:
        reasons.append("hardware_capacity_fail")
    return {"accepted": not reasons, "reasons": reasons, "max_latency_ms": round(latency, 4), "sink_interval_ms": round(cadence, 4), "sensor_fps": sensor_fps,
            "effective_clock_mhz": {node: round(cfg.set_clock_mhz, 3) for node, cfg in result.resolved.items()}, "bw_mbs": round(result.bw_total_mbs, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"], hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    report = {"assumptions": ["No measurements: camera/APV capacity, CPU placement, bitrate and storage times are assumptions.", "Clock selection is conditional timing feasibility, not measured power optimization.", "Mean release jitter stays 1ms in all timing cases; no tail distribution was supplied.", "Shared camera HW reservations are conservative; dual RT multiplexing requires runtime confirmation.", "CPU active power, stats with unknown size, thermal throttling and storage burst/queue limits are uncharacterized."], "verified_graphs": [], "exploration": []}
    for scenario in ["uc-camera-recording", "uc-camera-recording-apv"]:
        raw = read(FIXTURE / "02_definition" / (scenario + ".yaml"))
        Usecase.model_validate(raw)
        for v in raw["variants"]:
            graph = graph_from_fixture(raw, v["id"], catalog)
            inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=1))
            assert nx.is_directed_acyclic_graph(nx.DiGraph((e["from"], e["to"]) for e in inputs.timeline_edges)), v["id"]
            for port in inputs.port_transfers:
                names = {m["name"] for m in catalog[port.ip_ref].capabilities.get("properties", {}).get("modules", [])}
                assert port.port in names, (v["id"], port.node_id, port.port)
            report["verified_graphs"].append(v["id"])
        targets = PRIORITY + ["cam-rec-pip-fhd30", "cam-rec-pip-uhd30", "cam-rec-r1-fhd30-portrait", "cam-rec-r1-uhd30-portrait"] if scenario == "uc-camera-recording" else [v["id"] for v in raw["variants"]]
        for id in targets:
            for case in ["min", "mean", "max"]:
                candidates = []
                selected = None
                for clock in CLOCKS:
                    graph = graph_from_fixture(raw, id, catalog)
                    graph.variant.design_conditions["sw_timing_case"] = case
                    for node in graph.pipeline_nodes:
                        if node["role"] not in {"sensor", "sw_task", "display_output", "display_controller"}:
                            graph.variant.node_configs.setdefault(node["id"], {}).setdefault("sim", {})["manual_clock_mhz"] = clock
                    inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=8, debug_trace=True))
                    result = run_simulation(inputs, dvfs_tables={})
                    check = {"clock_mhz": clock, **assess_priority(graph, inputs, result)}
                    candidates.append(check)
                    if selected is None and check["accepted"]:
                        selected = (deepcopy(inputs), deepcopy(result), check)
                chosen_inputs, chosen_result, chosen_check = selected or (inputs, result, check)
                report["exploration"].append({"scenario": scenario, "variant": id, "case": case, "selected_clock_mhz": selected[2]["clock_mhz"] if selected else None,
                    "runtime_confirmation_required": bool(graph.variant.design_conditions.get("sensor_runtime_confirmation") or graph.variant.design_conditions.get("sensor_cadence_policy")), "candidates": candidates})
                if args.write_evidence and case == "mean":
                    chosen_result.warnings.extend(report["assumptions"])
                    chosen_result.warnings.append("Priority verification: " + json.dumps(chosen_check))
                    if selected is None:
                        chosen_result.feasible = False
                        chosen_result.infeasible_reason = ", ".join(chosen_check["reasons"])
                    chosen_result.calculation_trace["priority_verification"] = chosen_check
                    evidence = build_simulation_evidence(chosen_result, project_ref=raw["project_ref"], params_hash=params_hash(chosen_inputs),
                        evidence_id="sim-priority-" + id + "-mean-20260913",
                        execution_context=ExecutionContext(silicon_rev="EVT1", sw_baseline_ref="sw-vendor-v1.2.3", thermal="room", method="calculation"), timestamp="2026-09-13T00:00:00+09:00")
                    (FIXTURE / "03_evidence" / (evidence.id + ".yaml")).write_text(yaml.safe_dump(evidence.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True), encoding="utf-8")
    (FIXTURE / "priority_recording_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    sync_import_bundle()
    print(json.dumps({"graphs": len(report["verified_graphs"]), "cases": len(report["exploration"]), "mean": [{k:v for k,v in r.items() if k!="candidates"} for r in report["exploration"] if r["case"]=="mean"]}, indent=2))


if __name__ == "__main__":
    main()
