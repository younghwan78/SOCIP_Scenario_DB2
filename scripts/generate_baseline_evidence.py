"""SYNTHETIC evidence for the three baseline Camera Recording variants (Exynos2600 fixture).

Baselines: cam-rec-r1-uhd30-vdis, cam-rec-f1-uhd60, cam-rec-r1-8k30-psm. For each one this fills what
every menu needs — Scenario 예측/실측, Pipeline Timing (Trace · 주기·지연 · 예측↔실측), 예측↔실측 calibration,
CPU what-if (MID 재분배 / 자동 탐색):

* simulation evidence when the variant has none (same simulator / clock grid as the rear gap fill)
  -> ``sim-baseline-<variant>-mean-20261004``
* a SYNTHETIC measurement ``meas-synth-baseline-<variant>-evt1-20261004`` with
  - a measured-like timing trace: the simulation timeline perturbed per stage (RT ≈ sensor locked,
    NRT / M2M / codec a few % slower, SW 15–45 % slower) with per-frame jitter, 12 frames
  - sw_task_timing digested from that trace
  - a per-frame CPU profile (task × cluster cycles / stall / bus, thread split, cluster frequency
    residency + gating, DSU residency) consistent with the EAS model on pmp-exynos2600-v2
  - rail power ONLY when the variant has no measurement with rails yet (rescaled from the reference
    capture like generate_rear_recording_evidence.py); otherwise the existing measurement stays the
    power reference and this one carries trace + CPU only

NOT silicon data: provenance.device_id SYNTHETIC, collection_method synthetic_fixture.

    python scripts/generate_baseline_evidence.py            # dry run (prints a summary)
    python scripts/generate_baseline_evidence.py --write    # writes into 03_evidence
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_rear_recording_evidence import (  # noqa: E402
    EVIDENCE, REF_MEAS, REF_SIM, SCENARIO, existing_evidence, find_sim, jitter, load_catalog, simulate, sim_evidence,
    synth_measurement, sw_tasks,
)
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.models.capability.power_model import PowerModelParams  # noqa: E402
from scenario_db.models.evidence.measurement import MeasurementEvidence  # noqa: E402
from scenario_db.sim.cpu_power import CpuPowerModel  # noqa: E402
from scenario_db.sim.cpu_profile import cpu_profile_from_observations  # noqa: E402
from scenario_db.sim.cpu_sched import SweepSpec, cpu_sweep  # noqa: E402

BASELINES = ["cam-rec-r1-uhd30-vdis", "cam-rec-f1-uhd60", "cam-rec-r1-8k30-psm"]
DATE = "20261004"
STAMP = "2026-10-04T10:00:00+09:00"
FRAMES = 12
NOTE = ("SYNTHETIC baseline fixture — not silicon data. Trace = simulation timeline perturbed per stage; "
        "CPU profile = assumed task loads placed on MID_LF0 / MID_LF1 / MID_HF. Replace with a real capture.")
TOPOLOGY = FIXTURE / "00_hw" / "pmp-exynos2600-v2.yaml"
# RT is locked to the sensor; downstream HW runs a little slower than modelled; SW a lot slower
STAGE_SCALE = {"sensor": (1.0, 0.0), "rt": (1.0, 0.01), "nrt": (1.06, 0.04), "m2m": (1.08, 0.05),
               "codec": (1.05, 0.03), "display": (1.03, 0.02), "sw": (1.3, 0.15)}
REF_MHZ = {"MID_LF0": 1600.0, "MID_LF1": 1600.0, "MID_HF": 2000.0, "BIG": 3000.0}
RT_NODES = ("csis", "pdp", "byrp", "rgbp", "yuvsc", "mlsc")
NRT_NODES = ("mtnr", "msnr", "yuvp", "mcsc")


def stage_of(node: str, task_type: str) -> str:
    n = node.lower()
    if n.startswith("sensor"):
        return "sensor"
    if task_type == "sw" or n in ("post_crta", "pre_me_rta", "post_irta", "eis", "mpeg_writer", "storage_write"):
        return "sw"
    if n.startswith(RT_NODES):
        return "rt"
    if n.startswith(NRT_NODES):
        return "nrt"
    if n.startswith(("mfc", "apv", "codec")):
        return "codec"
    if n.startswith(("dpu", "panel", "display")):
        return "display"
    return "m2m"


def measured_trace(sim: dict, vid: str, fps: float) -> list[dict]:
    """Simulation timeline -> measured-like trace (FRAMES frames, frame-relative perturbation)."""
    events = [e for e in sim.get("timeline_events") or [] if e.get("task_id") and e.get("start_ms") is not None]
    period = 1000.0 / fps
    by_frame: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        by_frame[int(e.get("frame_index") or 0)].append(e)
    frames = sorted(by_frame)
    if not frames:
        return []
    src_frames = frames[1:] if len(frames) > 2 else frames      # drop the warm-up frame as the pattern
    out: list[dict] = []
    for f in range(FRAMES):
        sf = src_frames[f % len(src_frames)]
        evs = by_frame[sf]
        origin = min(e["start_ms"] for e in evs)
        base = f * period
        for e in sorted(evs, key=lambda x: x["start_ms"]):
            node = str(e.get("node_id") or e["task_id"].split("#")[0])
            stage = stage_of(node, str(e.get("task_type") or "hw"))
            scale, spread = STAGE_SCALE[stage]
            dur_k = scale * jitter(f"{vid}|{node}", spread * 0.5) * jitter(f"{vid}|{node}|{f}", spread * 0.6)
            off_k = 1.0 if stage in ("sensor", "rt") else 1.0 + (scale - 1.0) * 0.6
            rel = (e["start_ms"] - origin) * off_k + (jitter(f"{vid}|{node}|s{f}", 1.0) - 1.0) * (0.05 if stage in ("sensor", "rt") else 0.25)
            dur = (e["end_ms"] - e["start_ms"]) * dur_k
            start = max(base, base + rel)
            ev = {"task_id": f"{node}#f{f}", "node_id": node, "hw_name": e.get("hw_name"), "task_type": e.get("task_type"),
                  "frame_index": f, "start_ms": round(start, 4), "end_ms": round(start + max(dur, 0.01), 4),
                  "resource_id": e.get("resource_id"),
                  "predecessors": [f"{p.split('#')[0]}#f{f}" for p in e.get("predecessors") or []]}
            out.append({k: v for k, v in ev.items() if v is not None})
    return out


def sw_timing_from_trace(trace: list[dict], fps: float) -> list[dict]:
    durs: dict[str, list[float]] = defaultdict(list)
    for e in trace:
        if stage_of(e["node_id"], str(e.get("task_type") or "")) == "sw":
            durs[e["node_id"]].append(e["end_ms"] - e["start_ms"])
    out = []
    for task, v in sorted(durs.items()):
        v = sorted(v)
        out.append({"task": task, "timing_scope": "exclusive_sw", "min_ms": round(v[0], 3), "mean_ms": round(statistics.mean(v), 3),
                    "p50_ms": round(statistics.median(v), 3), "p95_ms": round(v[min(len(v) - 1, int(0.95 * len(v)))], 3),
                    "max_ms": round(v[-1], 3), "samples": len(v), "count_per_frame": 1.0, "value_source": "assumed", "source_note": NOTE})
    return out


def frame_latency(trace: list[dict]) -> float | None:
    per: dict[int, list[float]] = defaultdict(list)
    for e in trace:
        per[e["frame_index"]].append(e["start_ms"]); per[e["frame_index"]].append(e["end_ms"])
    lat = [max(v) - min(v) for v in per.values() if v]
    return statistics.mean(lat) if lat else None


# ---------------------------------------------------------------- CPU profile
def cpu_tasks(vid: str, graph, fps: float, sw_meas: dict[str, float]) -> list[tuple[str, str, float, list[float]]]:
    """(task, home cluster, ms per frame at the home cluster's mean frequency, thread split)."""
    dc = graph.variant.design_conditions or {}
    px = {"FHD": 1.0, "QHD": 1.8, "UHD": 4.0, "8K": 16.0}.get(str(dc.get("resolution") or "UHD"), 4.0)
    load = (px / 4.0) ** 0.35                      # HAL / codec bookkeeping grows sub-linearly with pixels
    heavy = px >= 16.0
    tasks: list[tuple[str, str, float, list[float]]] = []
    for t in sw_tasks(graph):                       # the pipeline's own CPU tasks (measured-like means)
        name = t["task"]
        ms = sw_meas.get(name, float(t["mean_ms"]) * 1.25)
        home = "MID_LF1" if name in ("mpeg_writer", "storage_write") else ("MID_HF" if heavy and name == "post_irta" else "MID_LF0")
        split = [1.0] if ms < 1.0 else [0.6, 0.4] if ms < 4.0 else [0.45, 0.35, 0.2]
        tasks.append((name, home, ms, split))
    have = {t[0] for t in tasks}
    extra = [("camera_hal_request", "MID_LF0", 7.5 * load, [0.5, 0.3, 0.2]), ("camera_hal_result", "MID_LF0", 4.8 * load, [0.6, 0.4]),
             ("aaa_ae_awb", "MID_LF0", 6.0, [0.6, 0.4]), ("af_algo", "MID_LF0", 2.8, [1.0]),
             ("face_det_post", "MID_LF0", 3.5, [0.6, 0.4]),
             ("c2_encoder", "MID_LF1", 3.0 * load, [0.7, 0.3]), ("surfaceflinger", "MID_LF1", 3.6, [0.7, 0.3]),
             ("audio_hal", "MID_LF1", 0.9, [1.0])]
    if "mpeg_writer" not in have:
        extra.append(("mpeg_writer", "MID_LF1", 1.4 * load, [1.0]))
    tasks += [(n, h, ms * jitter(vid + n, 0.08), s) for n, h, ms, s in extra]
    return tasks


def cpu_observations(vid: str, tasks, fps: float, model: CpuPowerModel, mean_mhz: dict[str, float],
                     residency: dict[str, dict[float, float]], gating: dict[str, tuple[float, float, float]],
                     dsu: dict[float, float]) -> list[dict]:
    obs: list[dict] = []
    tid = 2000 + int(jitter(vid, 0.5) * 100)

    def add(metric: str, kind: str, ref: str, unit: str, value: float) -> None:
        obs.append({"metric_id": metric, "scope": {"kind": kind, "ref": ref}, "unit": unit, "value": round(value, 6 if unit == "ratio" else 1)})

    for name, home, ms, split in tasks:
        # ms = task time at the reference frequency of its cluster (fixed load; residency only reports where EAS ran it)
        cycles = ms * REF_MHZ[home] * 1000.0 * 0.85              # 15 % of the wall time is memory stall
        stall = ms * REF_MHZ[home] * 1000.0 * 0.15
        ref = f"{name}@{home}"
        add("cpu.cycles_pf", "task_cluster", ref, "count", cycles)
        add("cpu.instructions_pf", "task_cluster", ref, "count", cycles * 0.78)
        add("cpu.stall_cycles_pf", "task_cluster", ref, "count", stall)
        add("cpu.bus_bytes_pf", "task_cluster", ref, "bytes", ms * 0.55e6)
        if len(split) > 1:
            for share in split:
                tid += 1
                add("cpu.thread_cycles_pf", "task_thread", f"{ref}#{tid}", "count", cycles * share)
    other = {"MID_LF0": 2.4, "MID_LF1": 2.0, "MID_HF": 1.1}           # kernel / unmapped threads
    for cl, ms in other.items():
        cycles = ms * REF_MHZ[cl] * 1000.0
        add("cpu.cycles_pf", "task_cluster", f"(other)@{cl}", "count", cycles * 0.8)
        add("cpu.stall_cycles_pf", "task_cluster", f"(other)@{cl}", "count", cycles * 0.2)
        add("cpu.instructions_pf", "task_cluster", f"(other)@{cl}", "count", cycles * 0.6)
        add("cpu.bus_bytes_pf", "task_cluster", f"(other)@{cl}", "bytes", ms * 0.4e6)
    for cl, res in residency.items():
        for mhz, share in res.items():
            add("cpu.freq_residency", "cluster_freq", f"{cl}@{int(mhz)}", "ratio", share)
        active, cg, pg = gating[cl]
        add("cpu.active_ratio", "cluster", cl, "ratio", active)
        add("cpu.clock_gated_ratio", "cluster", cl, "ratio", cg)
        add("cpu.power_gated_ratio", "cluster", cl, "ratio", pg)
    for mhz, share in dsu.items():
        add("cpu.freq_residency", "cluster_freq", f"DSU@{int(mhz)}", "ratio", share)
    return obs


def cpu_profile(vid: str, graph, fps: float, sw_meas: dict[str, float]) -> tuple[list[dict], list[dict], dict]:
    """Two passes: place with a guess, read the EAS frequencies back, emit residency around them."""
    model = CpuPowerModel.from_params(PowerModelParams.model_validate(yaml.safe_load(TOPOLOGY.read_text(encoding="utf-8"))))
    opps = {c.name: [o.mhz for o in c.opps] for c in model.clusters}
    tasks = cpu_tasks(vid, graph, fps, sw_meas)
    mean = {c: opps[c][-2] for c in opps}
    res = {c: {opps[c][-2]: 1.0} for c in opps}
    gat = {c: (0.3, 0.3, 0.4) for c in opps}
    dsu = {900.0: 1.0}
    summary: dict = {}
    for _ in range(3):
        obs = cpu_observations(vid, tasks, fps, model, mean, res, gat, dsu)
        prof = cpu_profile_from_observations(obs)
        r = cpu_sweep(prof, target=model, fps=fps, spec=SweepSpec(sweep_clusters={}, max_cases=50, top=1))
        ref = r["measured_placement"]
        new_mean = {}
        for c, row in ref["clusters"].items():
            f = row["mhz"]
            i = opps[c].index(f) if f in opps[c] else 0
            lo = opps[c][max(0, i - 1)]
            main = 0.78 if lo != f else 1.0
            res[c] = {f: main} | ({lo: round(1 - main, 3)} if lo != f else {})
            new_mean[c] = sum(m * s for m, s in res[c].items())
            busy = min(0.95, row["util"])
            gat[c] = (round(busy, 4), round((1 - busy) * 0.45, 4), round((1 - busy) * 0.55, 4))
        dsu_top = (ref.get("dsu") or {}).get("mhz") or 900.0
        dsu = {dsu_top: 0.7, 400.0: 0.3} if dsu_top > 400 else {400.0: 1.0}
        mean = {c: new_mean.get(c, mean[c]) for c in opps}
        summary = {"clusters_mhz": {c: row["mhz"] for c, row in ref["clusters"].items()}, "cpu_mw": round(ref["total_mw"], 1),
                   "feasible": ref["feasible"], "tasks": len(tasks)}
    breakdown = [{"cluster": c, "avg_freq_mhz": round(mean[c], 1), "util_pct": round(100 * gat[c][0], 1),
                  "freq_residency": [{"freq_mhz": m, "ratio": s} for m, s in sorted(res[c].items())]} for c in opps if c != "BIG"]
    return obs, breakdown, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    raw = read(FIXTURE / "02_definition" / f"{SCENARIO}.yaml")
    catalog = load_catalog.cache = load_catalog()
    have = existing_evidence()
    ref, ref_sim = read(EVIDENCE / f"{REF_MEAS}.yaml"), read(EVIDENCE / f"{REF_SIM}.yaml")
    rc = 0
    for vid in BASELINES:
        if args.only and vid not in args.only:
            continue
        graph = graph_from_fixture(raw, vid, catalog)
        fps = float((graph.variant.design_conditions or {}).get("fps") or 30)
        row: dict = {"variant": vid, "had": sorted(have.get(vid, set())), "added": []}
        sim = find_sim(vid)
        if sim is None:
            selected, last = simulate(raw, vid, catalog)
            sim = sim_evidence(raw, vid, selected, last)
            sim["id"] = f"sim-baseline-{vid}-mean-{DATE}"
            row["sim_clock_mhz"] = selected[2]["clock_mhz"] if selected else None
            row["added"].append(sim["id"])
            if args.write:
                (EVIDENCE / f"{sim['id']}.yaml").write_text(yaml.safe_dump(sim, sort_keys=False, allow_unicode=True), encoding="utf-8")
        trace = measured_trace(sim, vid, fps)
        sw = sw_timing_from_trace(trace, fps)
        obs, breakdown, cpu_summary = cpu_profile(vid, graph, fps, {t["task"]: t["mean_ms"] for t in sw})
        lat = frame_latency(trace)
        has_rails = any(read(p).get("vdd_power") for p in EVIDENCE.glob("meas-*.yaml")
                        if p.name.startswith(("meas-cam", "meas-synth-cam")) and vid in p.name)
        if has_rails:
            doc = {"id": f"meas-synth-baseline-{vid}-evt1-{DATE}", "schema_version": "2.2", "kind": "evidence.measurement",
                   "scenario_ref": SCENARIO, "variant_ref": vid, "project_ref": raw["project_ref"], "measured_at": STAMP,
                   "derived_from": [sim["id"]],
                   "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "room",
                                         "ambient_temp_c": 25.0, "power_state": "discharging", "method": "measurement"},
                   "provenance": {"device_id": "SYNTHETIC", "collection_method": "synthetic_fixture",
                                  "collection_tool_versions": {"generator": "generate_baseline_evidence.py"},
                                  "sample_count": 1, "duration_per_sample_s": 30.0, "confidence_level": 0.95},
                   "aggregation": {"strategy": "mean_over_capture"}, "kpi": {}}
        else:
            doc = synth_measurement(raw, vid, graph, sim, ref, ref_sim)
            doc["id"] = f"meas-synth-baseline-{vid}-evt1-{DATE}"
            doc["measured_at"] = STAMP
            doc["provenance"]["collection_tool_versions"] = {"generator": "generate_baseline_evidence.py"}
        if lat is not None:
            doc["kpi"]["frame_latency_ms"] = {"mean": round(lat, 2), "n": FRAMES}
        doc["kpi"]["fps_effective"] = round(fps * 0.999, 2)
        doc["timeline_events"] = trace
        doc["sw_task_timing"] = sw
        doc["metric_observations"] = obs
        doc["cpu_breakdown"] = breakdown if has_rails else breakdown + [b for b in doc.get("cpu_breakdown", []) if b["cluster"] not in {x["cluster"] for x in breakdown}]
        MeasurementEvidence.model_validate(doc)
        row["added"].append(doc["id"])
        row.update({"rails": not has_rails, "trace_events": len(trace), "frame_latency_ms": round(lat or 0, 2), "cpu": cpu_summary,
                    "sw": {t["task"]: t["mean_ms"] for t in sw}})
        if args.write:
            (EVIDENCE / f"{doc['id']}.yaml").write_text(
                f"# SYNTHETIC baseline measurement ({vid}) — not silicon data.\n"
                f"# Generated by scripts/generate_baseline_evidence.py from {sim['id']}"
                f"{'' if has_rails else f' and {REF_MEAS}'}.\n"
                + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return rc


load_catalog.cache = {}  # type: ignore[attr-defined]

if __name__ == "__main__":
    raise SystemExit(main())
