"""Simulation inputs of one variant, as the Pipeline "Sim 입력" lens shows them.

Per active pipeline node: cadence (frame path or own cadence), execution time, the load term the
simulation charges (SW: CPU ms/s, HW: duty %), power and bandwidth from the driver model or the
newest simulation evidence, and checks of the defined SW timing against measured SW timing.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.services.calibration import _sim_evidence, _when, _iso
from scenario_db.comparison.measurement_selection import is_physical, is_synthetic
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph, load_canonical_graph
from scenario_db.exceptions import NotFoundError
from scenario_db.sim.driver_models import evaluate_graph
from scenario_db.sim.timing_profiles import timing_case, timing_profiles

# defined SW mean vs measured mean beyond this share is reported as a value conflict
CONFLICT_PCT = 30.0


def _fps(graph: CanonicalScenarioGraph) -> float | None:
    conditions = graph.variant.design_conditions or {}
    for key in ("fps", "sensor_input_fps"):
        try:
            value = float(conditions.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _measured_task(node_id: str, measured: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    """Measured task for a node: same name, else ``<node>_<suffix>`` (eis -> eis_warp)."""
    if node_id in measured:
        return node_id, measured[node_id]
    hits = sorted(name for name in measured if name.startswith(f"{node_id}_"))
    return (hits[0], measured[hits[0]]) if len(hits) == 1 else None


def _bw_mbs(declared: Any) -> dict[str, float] | None:
    if not isinstance(declared, dict):
        return None
    return {key: round(float(declared.get(key) or 0.0) / 1000.0, 3) for key in ("read", "write")}


def build_sim_inputs(
    graph: CanonicalScenarioGraph,
    *,
    sim: Any | None = None,
    driver: dict[str, Any] | None = None,
    measured: tuple[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    fps = _fps(graph)
    case = timing_case(graph)
    profiles = timing_profiles(graph)
    configs = graph.variant.node_configs or {}
    hw_time = {str(t.get("node_id")): t.get("hw_time_ms") for t in (getattr(sim, "timing_breakdown", None) or [])
               if isinstance(t, dict)}
    ip_power = {(r.get("ip"), int(r.get("instance_index") or 0)): r.get("power_mW")
                for r in (getattr(sim, "ip_breakdown", None) or []) if isinstance(r, dict)}
    sim_bw: dict[str, dict[str, float]] = {}
    for item in getattr(sim, "dma_breakdown", None) or []:
        if isinstance(item, dict) and item.get("direction") in ("read", "write") and isinstance(item.get("bw_mbs"), (int, float)):
            acc = sim_bw.setdefault(str(item.get("node_id")), {"read": 0.0, "write": 0.0})
            acc[item["direction"]] += float(item["bw_mbs"])
    drivers = {str(r["node_id"]): r for r in (driver or {}).get("rows", []) if isinstance(r, dict)}
    measurement_ref, measured_tasks = measured or (None, {})

    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for node in graph.pipeline_nodes:
        node_id = str(node["id"])
        config = configs.get(node_id) or {}
        timeline = config.get("timeline") or {}
        period = float(timeline.get("period_ms") or 0.0)
        profile = profiles.get(node_id)
        kind = "sw" if node.get("role") == "sw_task" or profile is not None else "hw"

        rate: float | None
        duration: dict[str, Any] | None
        power: dict[str, Any] | None
        bw: dict[str, float] | None
        if period > 0:
            rate, path = 1000.0 / period, "independent"
        elif profile and profile.get("rate_hz"):
            rate, path = float(profile["rate_hz"]), "frame"
        elif profile and profile.get("count_per_frame") and fps:
            rate, path = fps * float(profile["count_per_frame"]), "frame"
        else:
            rate, path = fps, "frame"

        if profile:
            duration = {"mean_ms": profile.get(f"{case}_ms", profile.get("mean_ms")), "min_ms": profile.get("min_ms"),
                        "max_ms": profile.get("max_ms"), "p95_ms": profile.get("p95_ms"), "basis": "sw_timing",
                        "value_source": profile.get("value_source")}
        elif hw_time.get(node_id) is not None:
            duration = {"mean_ms": hw_time[node_id], "basis": "simulation", "value_source": "simulation"}
        elif timeline.get("duration_ms") is not None:
            duration = {"mean_ms": float(timeline["duration_ms"]), "basis": "node_config",
                        "value_source": timeline.get("value_source")}
        else:
            duration = None
        mean = float(duration["mean_ms"]) if duration and duration.get("mean_ms") is not None else None
        load = None
        if mean is not None and rate:
            load = {"cpu_ms_per_s": round(mean * rate, 3)} if kind == "sw" else {"duty_pct": round(mean * rate / 10.0, 3)}

        drv = drivers.get(node_id)
        if drv is not None:
            power = {"mw": drv.get("power_mw"), "basis": "driver_model",
                     "status": drv.get("power_status") or drv.get("status")}
            if drv.get("read_bytes_s") is not None or drv.get("write_bytes_s") is not None:
                bw = {key: round(float(drv.get(f"{key}_bytes_s") or 0.0) / 1e6, 3) for key in ("read", "write")}
            else:
                bw = _bw_mbs(drv.get("declared_bw_kb_s"))
        else:
            mw = ip_power.get((node.get("ip_ref"), int(node.get("instance_index") or 0)))
            power = {"mw": mw, "basis": "simulation"} if mw is not None else None
            bw = {k: round(v, 3) for k, v in sim_bw[node_id].items()} if node_id in sim_bw else _bw_mbs(config.get("bw_kb_s"))

        row: dict[str, Any] = {
            "node_id": node_id, "ip_ref": node.get("ip_ref"), "role": node.get("role"), "kind": kind,
            "cadence": {"path": path, "rate_hz": round(rate, 4) if rate else None,
                        "period_ms": round(1000.0 / rate, 4) if rate else None,
                        "per_frame": round(rate / fps, 4) if rate and fps else None,
                        "value_source": timeline.get("value_source") if period > 0 else None},
            "duration": duration, "load": load, "power": power, "bw_mbs": bw,
        }
        rows.append(row)

        hit = _measured_task(node_id, measured_tasks) if profile and mean is not None else None
        if hit and mean is not None and duration is not None and hit[1].get("mean_ms") is not None:
            task, stats = hit
            measured_mean = float(stats["mean_ms"])
            if measured_mean > 0 and abs(mean - measured_mean) / measured_mean * 100.0 > CONFLICT_PCT:
                checks.append({"kind": "value", "node_id": node_id,
                               "title": f"{node_id} 실행 시간: 정의 {mean:g} ms ↔ 실측 {measured_mean:g} ms",
                               "detail": f"sw_timing ({duration.get('value_source') or '출처 없음'}) 대비 실측 task {task} "
                                         f"({measurement_ref}) 차이 {abs(mean - measured_mean) / measured_mean * 100.0:.0f} %"})
        if drv is not None:
            checks.append({"kind": "info", "node_id": node_id,
                           "title": f"{node_id} power는 driver model 값",
                           "detail": "endpoint 추정값이며 simulation total power에는 더하지 않음"})

    sw_cpu = sum(r["load"]["cpu_ms_per_s"] for r in rows if r["load"] and "cpu_ms_per_s" in r["load"])
    return {
        "scenario_id": graph.scenario_id, "variant_id": graph.variant_id, "fps": fps, "timing_case": case,
        "simulation_ref": getattr(sim, "id", None), "measurement_ref": measurement_ref,
        "rows": rows,
        "totals": {"sw_cpu_ms_per_s": round(sw_cpu, 3),
                   "independent_nodes": sum(1 for r in rows if r["cadence"]["path"] == "independent")},
        "checks": checks,
    }


def _newest_measured_sw(db: Session, scenario_id: str, variant_id: str) -> tuple[str, dict[str, dict[str, Any]]] | None:
    rows: list[Any] = [r for r in (db.query(Evidence)
                                   .filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref == scenario_id,
                                           Evidence.variant_ref == variant_id)
                                   .all()) if r.sw_task_timing]
    if not rows:
        return None
    # physical capture first, synthetic fixtures last (same order as the calibration selection), then newest
    row = max(rows, key=lambda r: (is_physical(r.provenance), not is_synthetic(r.provenance), _when(_iso(r.measured_at)), str(r.id)))
    tasks: list[Any] = list(row.sw_task_timing or [])
    return str(row.id), {str(t["task"]): t for t in tasks if isinstance(t, dict) and t.get("task")}


def sim_inputs(db: Session, scenario_id: str, variant_id: str) -> dict[str, Any]:
    try:
        graph = load_canonical_graph(db, scenario_id, variant_id)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    sims = _sim_evidence(db, scenario_id, variant_id)
    return build_sim_inputs(graph, sim=sims[-1] if sims else None, driver=evaluate_graph(graph),
                            measured=_newest_measured_sw(db, scenario_id, variant_id))
