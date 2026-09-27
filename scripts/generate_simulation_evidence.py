"""Write simulation evidence (prediction + 8-frame timeline) for the variants of a DB folder.

The Pipeline page's timing diagram and the 예측 column need an evidence document with
``timeline_events``; derived projects (e.g. Exynos2700) start without any. For every
variant of the scenario this runs the simulator on the DB folder's own IP catalog
(SW timing case ``mean``, bounded clock grid 300..1000 MHz, first candidate meeting
cadence + 3-frame latency) and writes ``03_evidence/sim-<tag>-<variant>-mean-<date>.yaml``.

Values are MODEL output with assumed clocks/SW timing, not measurements. Rerun after
changing authoring (HW patches, SW timing, overlay); existing files are replaced.

    python scripts/generate_simulation_evidence.py db_Exynos2700_SM-S957B uc-cam-recording-e2700 [--only v1 v2]
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_is_v15_camera import CLOCKS, assess, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.models.evidence.common import ExecutionContext  # noqa: E402
from scenario_db.sim.adapter import build_simulation_inputs  # noqa: E402
from scenario_db.sim.models import SimulationRunConfig  # noqa: E402
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation  # noqa: E402

DATE = "20260927"
STAMP = "2026-09-27T00:00:00+09:00"
ASSUMPTIONS = [
    "No measurements: IP capacity, CPU placement, bitrate and storage times are inherited assumptions.",
    "Clock selection is conditional timing feasibility (grid 300..1000 MHz), not measured power optimization.",
    "SW timing case 'mean'; values inherited from the reference project unless overridden in authoring.",
]


def load_catalog(db: Path) -> dict[str, IpCatalog]:
    catalog = {}
    for path in (db / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    return catalog


def build_inputs(raw: dict, vid: str, catalog, clock: int):
    graph = graph_from_fixture(raw, vid, catalog)
    graph.variant.design_conditions["sw_timing_case"] = "mean"
    for node in graph.pipeline_nodes:
        if node["role"] not in {"sensor", "sw_task", "display_output", "display_controller"}:
            graph.variant.node_configs.setdefault(node["id"], {}).setdefault("sim", {})["manual_clock_mhz"] = clock
    return graph, build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=8, debug_trace=True))


def expected_params_hash(db: Path, scenario: str, evidence: dict) -> str:
    """params_hash the evidence would have if regenerated now (stale check after authoring changes)."""
    raw = read(db / "02_definition" / f"{scenario}.yaml")
    clock = evidence["calculation_trace"]["priority_verification"]["clock_mhz"]
    return params_hash(build_inputs(raw, evidence["variant_ref"], load_catalog(db), clock)[1])


def simulate(raw: dict, vid: str, catalog) -> tuple:
    selected, last = None, None
    for clock in CLOCKS:
        graph, inputs = build_inputs(raw, vid, catalog, clock)
        result = run_simulation(inputs, dvfs_tables={})
        fps = float((graph.variant.design_conditions or {}).get("fps") or inputs.config.fps)
        check = {"clock_mhz": clock, **assess(result, fps, 3.0)}
        last = (inputs, result, check)
        if check["accepted"]:
            selected = (deepcopy(inputs), deepcopy(result), check)
            break
    return selected, last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path)
    ap.add_argument("scenario")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tag", default="pred", help="evidence id tag: sim-<tag>-<variant>-mean-<date>")
    args = ap.parse_args()
    raw = read(args.db / "02_definition" / f"{args.scenario}.yaml")
    project = read(args.db / "02_definition" / f"{raw['project_ref']}.yaml")
    sw = (project.get("globals") or {}).get("default_sw_profile_ref") or project["metadata"].get("default_sw_profile_ref")
    catalog = load_catalog(args.db)
    out_dir = args.db / "03_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for v in raw["variants"]:
        vid = v["id"]
        if v.get("derived_from_variant") or (args.only and vid not in args.only):
            continue
        row = {"variant": vid}
        try:
            selected, last = simulate(raw, vid, catalog)
            inputs, result, check = selected or last
            result.warnings.extend(ASSUMPTIONS)
            result.warnings.append("Clock grid verification: " + json.dumps(check))
            if selected is None:
                result.feasible = False
                result.infeasible_reason = (f"no clock candidate met cadence/3-frame latency "
                                            f"(latency {check['max_frame_latency_ms']} ms, interval {check['average_sink_interval_ms']} ms)")
            result.calculation_trace["priority_verification"] = check
            ev = build_simulation_evidence(
                result, project_ref=raw["project_ref"], params_hash=params_hash(inputs),
                evidence_id=f"sim-{args.tag}-{vid}-mean-{DATE}",
                execution_context=ExecutionContext(silicon_rev="EVT0", sw_baseline_ref=sw, thermal="room", method="calculation"),
                timestamp=STAMP).model_dump(mode="json", exclude_none=True)
            (out_dir / f"{ev['id']}.yaml").write_text(
                "# SIMULATION (model prediction) - assumed clocks / SW timing, not a measurement.\n"
                "# Generated by scripts/generate_simulation_evidence.py; rerun after authoring changes.\n"
                + yaml.safe_dump(ev, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
            row.update(clock_mhz=check["clock_mhz"], accepted=check["accepted"],
                       total_power_mw=round(ev["kpi"].get("total_power_mw", 0.0), 1),
                       frames=len({e["frame_index"] for e in ev.get("timeline_events") or []}))
        except Exception as exc:  # keep going; report the variant
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return 1 if any("error" in r for r in report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
