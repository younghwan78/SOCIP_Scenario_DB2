"""Fill evidence gaps for rear-sensor Camera Recording variants.

For every base (non-derived) ``uc-camera-recording`` variant whose effective
``sensor_place`` is ``rear``:

* no simulation evidence  -> run the simulator (SW timing case ``mean``, the
  same bounded clock grid as ``verify_priority_recording.py``) and write
  ``sim-rear-<variant>-mean-20260925``;
* no measurement evidence -> write a SYNTHETIC measurement
  ``meas-synth-<variant>-evt1-20260925`` (skipped when the simulation found
  no clock candidate meeting cadence / 3-frame latency).

Synthetic measurements are NOT silicon data. Rails are the reference capture
(``meas-cam-rec-r1-uhd30-vdis``) rescaled per category with the variant's own
simulation (IP core / BW power) and SW load (CPU), plus a deterministic
per-variant perturbation. They exist to exercise 예측 ↔ 실측 / calibration
flows and are flagged by ``provenance.collection_method: synthetic_fixture``
and ``provenance.device_id: SYNTHETIC``. Replace them with real captures.

Run from implementation/:  python scripts/generate_rear_recording_evidence.py [--write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from copy import deepcopy
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_is_v15_camera import CLOCKS, FIXTURE, assess, graph_from_fixture, read  # noqa: E402

from scenario_db.comparison.calibration import measured_split, rail_category  # noqa: E402
from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.models.evidence.common import ExecutionContext  # noqa: E402
from scenario_db.models.evidence.measurement import MeasurementEvidence  # noqa: E402
from scenario_db.sim.adapter import build_simulation_inputs  # noqa: E402
from scenario_db.sim.models import SimulationRunConfig  # noqa: E402
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation  # noqa: E402

SCENARIO = "uc-camera-recording"
EVIDENCE = FIXTURE / "03_evidence"
REF_MEAS = "meas-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614"
REF_SIM = "sim-priority-cam-rec-r1-uhd30-vdis-mean-20260913"
DATE = "20260925"
STAMP = "2026-09-25T10:00:00+09:00"
T_N3 = 4.303  # two-sided 95 % t for n=3
SYNTH_NOTE = ("SYNTHETIC fixture — not silicon data. Reference rails rescaled by this variant's "
              "simulation (IP core, BW) and SW load (CPU); replace with a real capture.")
ASSUMPTIONS = [
    "No measurements: camera/APV capacity, CPU placement, bitrate and storage times are assumptions.",
    "Clock selection is conditional timing feasibility, not measured power optimization.",
    "Rear-recording gap fill (2026-09-25): same clock grid and SW timing case 'mean' as priority recording.",
]


def _header(path: Path) -> dict[str, str]:
    """kind / variant_ref / scenario_ref from the first lines (sim files are large)."""
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            m = re.match(r"^(kind|variant_ref|scenario_ref): (.+)$", line.rstrip())
            if m:
                out[m.group(1)] = m.group(2).strip("'\"")
            if len(out) == 3 or i > 40:
                break
    return out


def existing_evidence() -> dict[str, set[str]]:
    have: dict[str, set[str]] = {}
    for p in EVIDENCE.glob("*.yaml"):
        h = _header(p)
        if h.get("scenario_ref") == SCENARIO:
            have.setdefault(h.get("variant_ref", ""), set()).add(h.get("kind", "").split(".")[-1])
    return have


def jitter(key: str, span: float) -> float:
    """Deterministic factor in [1-span, 1+span]."""
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return 1.0 + span * (2 * h - 1)


def load_catalog() -> dict[str, IpCatalog]:
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    return catalog


def sw_tasks(graph) -> list[dict]:
    out = []
    for node in graph.pipeline_nodes:
        if node.get("role") != "sw_task":
            continue
        t = (graph.variant.node_configs or {}).get(node["id"], {}).get("sw_timing")
        if isinstance(t, dict) and t.get("mean_ms") is not None:
            out.append({"task": node["id"], **t})
    return out


def simulate(raw: dict, vid: str, catalog) -> tuple:
    selected, last = None, None
    for clock in CLOCKS:
        graph = graph_from_fixture(raw, vid, catalog)
        graph.variant.design_conditions["sw_timing_case"] = "mean"
        for node in graph.pipeline_nodes:
            if node["role"] not in {"sensor", "sw_task", "display_output", "display_controller"}:
                graph.variant.node_configs.setdefault(node["id"], {}).setdefault("sim", {})["manual_clock_mhz"] = clock
        inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=8, debug_trace=True))
        result = run_simulation(inputs, dvfs_tables={})
        fps = float((graph.variant.design_conditions or {}).get("fps") or inputs.config.fps)
        check = {"clock_mhz": clock, **assess(result, fps, 3.0)}
        last = (inputs, result, check)
        if check["accepted"]:
            selected = (deepcopy(inputs), deepcopy(result), check)
            break
    return selected, last


def sim_evidence(raw: dict, vid: str, selected, last) -> dict:
    inputs, result, check = selected or last
    result.warnings.extend(ASSUMPTIONS)
    result.warnings.append("Rear gap-fill verification: " + json.dumps(check))
    if selected is None:
        result.feasible = False
        result.infeasible_reason = f"no clock candidate met cadence/3-frame latency (latency {check['max_frame_latency_ms']} ms, interval {check['average_sink_interval_ms']} ms)"
    result.calculation_trace["rear_gapfill_verification"] = check
    ev = build_simulation_evidence(result, project_ref=raw["project_ref"], params_hash=params_hash(inputs),
                                   evidence_id=f"sim-rear-{vid}-mean-{DATE}",
                                   execution_context=ExecutionContext(silicon_rev="EVT1", sw_baseline_ref="sw-vendor-v1.2.3",
                                                                      thermal="room", method="calculation"),
                                   timestamp="2026-09-25T00:00:00+09:00")
    return ev.model_dump(mode="json", exclude_none=True)


def sim_numbers(doc: dict) -> dict:
    k = doc.get("kpi", {})
    ct = doc.get("calculation_trace") or {}
    trace = ct.get("rear_gapfill_verification") or ct.get("priority_verification") or {}
    return {"core": float(k.get("core_power_mw") or 0.0), "bw": float(k.get("bw_power_mw") or 0.0),
            "latency": trace.get("max_frame_latency_ms", trace.get("max_latency_ms")), "feasible": (doc.get("resolution_result") or {}).get("overall_feasibility")}


def find_sim(vid: str) -> dict | None:
    for p in sorted(EVIDENCE.glob("sim-*.yaml"), reverse=True):
        h = _header(p)
        if h.get("scenario_ref") == SCENARIO and h.get("variant_ref") == vid:
            return read(p)
    return None


def synth_measurement(raw: dict, vid: str, graph, sim: dict, ref: dict, ref_sim: dict) -> dict:
    dc = graph.variant.design_conditions or {}
    fps = float(dc.get("fps") or 30)
    rails = ref["vdd_power"]
    ref_split = measured_split(rails, None)["categories"]
    rs, ts = sim_numbers(ref_sim), sim_numbers(sim)
    ref_tasks = sw_tasks(graph_from_fixture(raw, ref["variant_ref"], load_catalog.cache))
    load = sum(t["mean_ms"] for t in sw_tasks(graph)) * fps
    ref_load = sum(t["mean_ms"] for t in ref_tasks) * float(30)
    target = {
        "ip": ref_split["ip"] * (ts["core"] / rs["core"] if rs["core"] else 1.0),
        "bw": ref_split["bw"] * (ts["bw"] / rs["bw"] if rs["bw"] else 1.0),
        "cpu": ref_split["cpu"] * min(2.5, max(0.6, 0.45 + 0.55 * (load / ref_load if ref_load else 1.0))),
        "other": ref_split["other"] * (0.85 + 0.15 * math.sqrt(ts["bw"] / rs["bw"])) if rs["bw"] else ref_split["other"],
    }
    out_rails = {}
    for name, r in rails.items():
        cat = rail_category(name, None, r.get("domain") if isinstance(r.get("domain"), str) else None)
        scale = target[cat] / ref_split[cat] if ref_split[cat] else 1.0
        p = float(r["power_mw"]) * scale * jitter(vid + name, 0.04)
        v = float(r["voltage_v"])
        row = {"voltage_v": v, "current_ma": round(p / v, 3) if v else 0.0, "power_mw": round(p, 3),
               "std_mw": round(float(r["std_mw"]) / float(r["power_mw"]) * p, 3)}
        if "domain" in r:
            row["domain"] = r["domain"]
        out_rails[name] = row
    total = sum(r["power_mw"] for r in out_rails.values())
    std = total * float(ref["kpi"]["total_power_mw"]["std"]) / float(ref["kpi"]["total_power_mw"]["mean"])
    half = T_N3 * std / math.sqrt(3)
    lat = ts["latency"] if isinstance(ts["latency"], (int, float)) and math.isfinite(ts["latency"]) else 3 * 1000 / fps * 0.3
    tasks = []
    for t in sw_tasks(graph):
        f = jitter(vid + t["task"], 0.25) + 0.15  # captures tend to run above the assumed mean
        mean = t["mean_ms"] * f
        mx = max(float(t.get("max_ms") or mean * 2), mean * 1.2) * jitter(vid + t["task"] + "max", 0.1) * 1.15
        tasks.append({"task": t["task"], "timing_scope": "exclusive_sw", "mean_ms": round(mean, 3), "p50_ms": round(mean * 0.95, 3),
                      "p95_ms": round(min(mx, mean * 1.35), 3), "max_ms": round(mx, 3), "samples": int(fps * 180),
                      "count_per_frame": 1.0, "value_source": "assumed", "source_note": SYNTH_NOTE})
    cpu_rails = {n: r for n, r in out_rails.items() if rail_category(n, None, r.get("domain")) == "cpu"}
    clusters = {"BIG": r"CPUCL3|BIG", "MID": r"CPUCL1|CPUCL2|MID", "LIT": r"CPUCL0|DSU"}
    cpu_breakdown = [{"cluster": c, "power_mw": round(sum(r["power_mw"] for n, r in cpu_rails.items() if re.search(pat, n)), 3)}
                     for c, pat in clusters.items()]
    doc = {
        "id": f"meas-synth-{vid}-evt1-{DATE}", "schema_version": "2.2", "kind": "evidence.measurement",
        "scenario_ref": SCENARIO, "variant_ref": vid, "project_ref": raw["project_ref"], "measured_at": STAMP,
        "derived_from": [ref["id"], sim["id"]],
        "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "room",
                              "ambient_temp_c": 25.0, "power_state": "discharging", "method": "measurement"},
        "provenance": {"device_id": "SYNTHETIC", "collection_method": "synthetic_fixture",
                       "collection_tool_versions": {"generator": "generate_rear_recording_evidence.py"},
                       "sample_count": 3, "duration_per_sample_s": 30.0, "confidence_level": 0.95},
        "aggregation": {"strategy": "mean_over_runs"},
        "kpi": {"total_power_mw": {"mean": round(total, 3), "p95": round(total + 0.93 * std, 3), "std": round(std, 3),
                                   "ci_95": [round(total - half, 3), round(total + half, 3)], "n": 3},
                "frame_latency_ms": {"mean": round(lat * jitter(vid + "lat", 0.05) * 1.08, 2),
                                     "p95": round(lat * 1.22, 2), "n": int(fps * 180)},
                "fps_effective": round(fps * 0.999, 2)},
        "vdd_power": out_rails, "cpu_breakdown": cpu_breakdown, "sw_task_timing": tasks,
        "timeline_events": [{"type": "note", "detail": SYNTH_NOTE}],
    }
    MeasurementEvidence.model_validate(doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write YAML into 03_evidence (default: dry run)")
    ap.add_argument("--only", nargs="*", help="limit to these variant ids")
    args = ap.parse_args()
    raw = read(FIXTURE / "02_definition" / f"{SCENARIO}.yaml")
    catalog = load_catalog.cache = load_catalog()
    have = existing_evidence()
    ref, ref_sim = read(EVIDENCE / f"{REF_MEAS}.yaml"), read(EVIDENCE / f"{REF_SIM}.yaml")
    report = []
    for v in raw["variants"]:
        vid = v["id"]
        if v.get("derived_from_variant") or (args.only and vid not in args.only):
            continue
        graph = graph_from_fixture(raw, vid, catalog)
        if (graph.variant.design_conditions or {}).get("sensor_place") != "rear":
            continue
        kinds = have.get(vid, set())
        row = {"variant": vid, "had": sorted(kinds), "added": []}
        try:
            sim = find_sim(vid)
            if "simulation" not in kinds:
                selected, last = simulate(raw, vid, catalog)
                sim = sim_evidence(raw, vid, selected, last)
                row["sim_clock_mhz"] = selected[2]["clock_mhz"] if selected else None
                row["sim_check"] = None if selected else {k: last[2][k] for k in ("max_frame_latency_ms", "average_sink_interval_ms", "cadence_ok")}
                row["added"].append(sim["id"])
                if args.write:
                    (EVIDENCE / f"{sim['id']}.yaml").write_text(yaml.safe_dump(sim, sort_keys=False, allow_unicode=True), encoding="utf-8")
            if "measurement" not in kinds and row.get("sim_check") is not None:
                # No accepted clock candidate: the device cannot sustain this config in the model,
                # so a rescaled "measurement" would be meaningless.
                row["skipped_measurement"] = "simulation infeasible (cadence/latency)"
            elif "measurement" not in kinds and sim is not None:
                meas = synth_measurement(raw, vid, graph, sim, ref, ref_sim)
                row["added"].append(meas["id"])
                row["synthetic_total_mw"] = meas["kpi"]["total_power_mw"]["mean"]
                if args.write:
                    body = yaml.safe_dump(meas, sort_keys=False, allow_unicode=True)
                    (EVIDENCE / f"{meas['id']}.yaml").write_text(
                        f"# SYNTHETIC measurement fixture ({vid}) — not silicon data.\n"
                        f"# Generated by scripts/generate_rear_recording_evidence.py from {REF_MEAS}\n"
                        f"# rescaled with {sim['id']}. Replace with a real rail/perfetto capture.\n" + body, encoding="utf-8")
        except Exception as exc:  # keep going; report the variant
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if args.write:
        (FIXTURE / "rear_recording_gapfill_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


load_catalog.cache = {}  # type: ignore[attr-defined]

if __name__ == "__main__":
    raise SystemExit(main())
