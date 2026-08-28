from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from scenario_db.models.evidence.common import Aggregation, ExecutionContext, RunInfo
from scenario_db.models.evidence.resolution import (
    OverallFeasibility,
    ResolutionResult,
    ViolationSummary,
)
from scenario_db.models.evidence.simulation import IpBreakdown, SimulationEvidence
from scenario_db.sim.bw_calc import calc_port_bw
from scenario_db.sim.debug_trace import build_calculation_trace
from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.models import (
    DVFSTable,
    IPTimingResult,
    PortBWResult,
    SimRunResult,
    SimulationInputs,
)
from scenario_db.sim.perf_calc import calc_processing_time_ms
from scenario_db.sim.power_model import resolve_power_model
from scenario_db.sim.timeline import build_timeline_events


def run_simulation(
    inputs: SimulationInputs,
    *,
    dvfs_tables: dict[str, DVFSTable] | None = None,
) -> SimRunResult:
    """Run formula simulation and optional SW/HW timeline simulation."""

    dvfs_tables = dvfs_tables or {}
    config = inputs.config
    power_model = resolve_power_model(config.power_model)
    effective_fps = float(config.fps or 30.0)
    # Mixed-rate pipelines: each port's traffic runs at its owning node's fps
    # (node sim-block override), falling back to the scenario fps.
    fps_by_node = {workload.node_id: workload.fps for workload in inputs.workloads}
    resolved = DvfsResolver(
        dvfs_tables,
        asv_group=config.asv_group,
        power_model=power_model,
    ).resolve(
        inputs.workloads,
        dvfs_overrides=config.dvfs_overrides,
    )
    dma_breakdown = [
        calc_port_bw(
            transfer,
            fps=fps_by_node.get(transfer.node_id, effective_fps),
            bw_power_coeff=config.bw_power_coeff,
            vbat=config.vbat,
            pmic_efficiency=config.pmic_efficiency,
            power_model=power_model,
        )
        for transfer in inputs.port_transfers
    ]
    timing_breakdown = [
        IPTimingResult(
            node_id=workload.node_id,
            ip_ref=workload.ip_ref,
            hw_name=workload.hw_name,
            hw_time_ms=calc_processing_time_ms(
                pixels=workload.pixels,
                set_clock_mhz=resolved[workload.node_id].set_clock_mhz,
                ppc=workload.sim_params.ppc,
                h_blank_margin=config.h_blank_margin,
            ),
            required_clock_mhz=resolved[workload.node_id].required_clock_mhz,
            set_clock_mhz=resolved[workload.node_id].set_clock_mhz,
            set_voltage_mv=resolved[workload.node_id].set_voltage_mv,
            feasible=resolved[workload.node_id].feasible,
            infeasible_reason=resolved[workload.node_id].infeasible_reason,
        )
        for workload in inputs.workloads
    ]
    timeline_events = []
    if config.include_timeline and inputs.timeline_tasks:
        timeline_tasks = _with_calculated_durations(inputs.timeline_tasks, timing_breakdown)
        frame_period_ms = (
            config.timeline_frame_period_ms
            or (1000.0 / config.fps if config.fps and config.fps > 0 else None)
        )
        timeline_events = build_timeline_events(
            timeline_tasks,
            inputs.timeline_edges,
            frame_count=config.timeline_frame_count,
            frame_period_ms=frame_period_ms,
            critical_budget_ms=frame_period_ms,
        )

    core_power_mw = sum(item.total_power_mw for item in resolved.values())
    bw_power_mw = sum(item.bw_power_mw for item in dma_breakdown)
    total_power_mw = core_power_mw + bw_power_mw
    total_power_ma = (
        total_power_mw / config.vbat / config.pmic_efficiency
        if config.vbat > 0 and config.pmic_efficiency > 0
        else 0.0
    )
    for item in resolved.values():
        item.total_power_ma = (
            item.total_power_mw / config.vbat / config.pmic_efficiency
            if config.vbat > 0 and config.pmic_efficiency > 0
            else 0.0
        )
    feasible = all(item.feasible for item in resolved.values())
    infeasible_reason = _first_infeasible_reason(timing_breakdown)
    bw_total_mbs = sum(item.bw_mbs for item in dma_breakdown)
    hw_time_max_ms = max((item.hw_time_ms for item in timing_breakdown), default=0.0)
    timeline_end_ms = max((item.end_ms for item in timeline_events), default=None)
    warnings = _simulation_warnings(
        inputs,
        core_power_mw=core_power_mw,
        hw_time_max_ms=hw_time_max_ms,
    )
    calculation_trace = None
    if config.debug_trace:
        calculation_trace = build_calculation_trace(
            inputs,
            dvfs_tables=dvfs_tables,
            resolved=resolved,
            dma_breakdown=dma_breakdown,
            timing_breakdown=timing_breakdown,
            timeline_events=timeline_events,
            core_power_mw=core_power_mw,
            bw_power_mw=bw_power_mw,
            total_power_mw=total_power_mw,
            total_power_ma=total_power_ma,
            bw_total_mbs=bw_total_mbs,
            hw_time_max_ms=hw_time_max_ms,
            timeline_end_ms=timeline_end_ms,
            effective_fps=effective_fps,
        )
        calculation_trace["warnings"] = list(warnings)

    return SimRunResult(
        scenario_id=inputs.scenario_id,
        variant_id=inputs.variant_id,
        total_power_mw=total_power_mw,
        total_power_ma=total_power_ma,
        core_power_mw=core_power_mw,
        bw_power_mw=bw_power_mw,
        bw_total_mbs=bw_total_mbs,
        hw_time_max_ms=hw_time_max_ms,
        timeline_end_ms=timeline_end_ms,
        feasible=feasible,
        infeasible_reason=infeasible_reason,
        resolved=resolved,
        dma_breakdown=dma_breakdown,
        timing_breakdown=timing_breakdown,
        timeline_events=timeline_events,
        external_devices=inputs.external_devices,
        topology_order=inputs.topology_order,
        vdd_power=_vdd_power(resolved, dma_breakdown, memory_rail=config.memory_rail),
        power_breakdown=_power_breakdown(
            resolved,
            dma_breakdown,
            memory_rail=config.memory_rail,
            power_model=power_model,
        ),
        warnings=warnings,
        calculation_trace=calculation_trace,
    )


def build_simulation_evidence(
    result: SimRunResult,
    *,
    execution_context: ExecutionContext,
    project_ref: str | None = None,
    params_hash: str | None = None,
    evidence_id: str | None = None,
    timestamp: str | None = None,
) -> SimulationEvidence:
    """Convert a run result into a persistable SimulationEvidence model."""

    feasibility = (
        OverallFeasibility.production_ready
        if result.feasible
        else OverallFeasibility.infeasible
    )
    critical_events = [event for event in result.timeline_events if event.critical]
    return SimulationEvidence(
        id=evidence_id or _evidence_id(result, params_hash),
        schema_version="2.2",
        kind="evidence.simulation",
        scenario_ref=result.scenario_id,
        variant_ref=result.variant_id,
        project_ref=project_ref,
        execution_context=execution_context,
        resolution_result=ResolutionResult(
            overall_feasibility=feasibility,
            violation_summary=ViolationSummary(
                total=0 if result.feasible else 1,
                fail_fast=0 if result.feasible else 1,
            ),
        ),
        run=RunInfo(
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            tool="scenariodb-sim",
            tool_version="0.1.0",
            source="calculated",
        ),
        aggregation=Aggregation(strategy="single_run"),
        kpi={
            "total_power_mw": result.total_power_mw,
            "total_power_ma": result.total_power_ma,
            "core_power_mw": result.core_power_mw,
            "bw_power_mw": result.bw_power_mw,
            "total_bw_mbs": result.bw_total_mbs,
            "hw_time_max_ms": result.hw_time_max_ms,
            "timeline_end_ms": result.timeline_end_ms or 0.0,
            "critical_path_ms": max((event.end_ms for event in critical_events), default=0.0),
            "critical_path_task_count": len(critical_events),
        },
        ip_breakdown=[
            IpBreakdown(
                ip=resolved.ip_ref,
                instance_index=0,
                power_mW=resolved.total_power_mw,
            )
            for resolved in result.resolved.values()
            if resolved.ip_ref
        ],
        dma_breakdown=result.dma_breakdown,
        timing_breakdown=result.timing_breakdown,
        dvfs_breakdown=list(result.resolved.values()),
        timeline_events=result.timeline_events,
        external_devices=result.external_devices,
        topology_order=result.topology_order,
        vdd_power=result.vdd_power,
        power_breakdown=result.power_breakdown or None,
        params_hash=params_hash,
        calculation_trace=result.calculation_trace,
    )


def params_hash(inputs: SimulationInputs) -> str:
    payload = inputs.model_dump(mode="json", exclude_none=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _with_calculated_durations(
    tasks: list[dict],
    timing_breakdown: list[IPTimingResult],
) -> list[dict]:
    timing_by_node = {item.node_id: item.hw_time_ms for item in timing_breakdown}
    timing_by_hw = {item.hw_name: item.hw_time_ms for item in timing_breakdown}
    result = []
    for task in tasks:
        updated = dict(task)
        if not float(updated.get("duration_ms") or 0.0):
            updated["duration_ms"] = (
                timing_by_node.get(str(updated.get("node_id")))
                or timing_by_node.get(str(updated.get("id")))
                or timing_by_hw.get(str(updated.get("hw_name")))
                or 0.0
            )
        result.append(updated)
    return result


def _vdd_power(
    resolved: dict[str, object],
    dma_breakdown: list[PortBWResult],
    *,
    memory_rail: str,
) -> dict[str, dict[str, float]]:
    """Per-rail power. BW-induced (DRAM/interconnect) power sits on the memory
    rail — where a bench actually measures it — not on the initiating IP's
    rail, so per-rail calibration factors compare like with like."""
    grouped: dict[str, dict[str, float]] = {}
    for item in resolved.values():
        vdd = getattr(item, "vdd", None)
        if not vdd:
            continue
        bucket = grouped.setdefault(vdd, {"core_mw": 0.0, "bw_mw": 0.0, "total_mw": 0.0})
        bucket["core_mw"] += float(getattr(item, "total_power_mw", 0.0))
    bw_total = sum(dma.bw_power_mw for dma in dma_breakdown)
    if bw_total > 0:
        bucket = grouped.setdefault(
            memory_rail, {"core_mw": 0.0, "bw_mw": 0.0, "total_mw": 0.0}
        )
        bucket["bw_mw"] += bw_total
    for bucket in grouped.values():
        bucket["total_mw"] = bucket["core_mw"] + bucket["bw_mw"]
    return grouped


def _power_breakdown(
    resolved: dict[str, object],
    dma_breakdown: list[PortBWResult],
    *,
    memory_rail: str,
    power_model,
) -> dict:
    """Three-bucket decomposition aligned with what a bench can measure:
    per-IP core power, memory (BW-driven) power, and CPU/cluster power.
    The cpu bucket is structural for now — SW tasks carry no compute model
    yet — so comparison/calibration schemas stay stable when it lands."""
    ip_by_rail: dict[str, float] = {}
    ip_by_node: dict[str, float] = {}
    for node_id, item in resolved.items():
        power = float(getattr(item, "total_power_mw", 0.0))
        ip_by_node[node_id] = round(power, 6)
        vdd = getattr(item, "vdd", None)
        if vdd:
            ip_by_rail[vdd] = ip_by_rail.get(vdd, 0.0) + power
    ip_total = sum(ip_by_node.values())
    memory_total = sum(dma.bw_power_mw for dma in dma_breakdown)
    total = ip_total + memory_total
    return {
        "model": {"id": power_model.model_id, "version": power_model.version},
        "ip": {
            "total_mw": round(ip_total, 6),
            "by_rail": {rail: round(mw, 6) for rail, mw in sorted(ip_by_rail.items())},
            "by_node": ip_by_node,
        },
        "memory": {
            "total_mw": round(memory_total, 6),
            "rail": memory_rail,
        },
        "cpu": {
            "total_mw": 0.0,
            "by_cluster": {},
        },
        "total_mw": round(total, 6),
    }


def _first_infeasible_reason(timing_breakdown: list[IPTimingResult]) -> str | None:
    for item in timing_breakdown:
        if not item.feasible:
            return item.infeasible_reason
    return None


def _simulation_warnings(
    inputs: SimulationInputs,
    *,
    core_power_mw: float,
    hw_time_max_ms: float,
) -> list[str]:
    warnings = list(inputs.warnings)
    has_compute_workload = bool(inputs.workloads)
    if has_compute_workload and core_power_mw <= 0:
        warnings.append(
            "All compute IP core power is zero; check capabilities.sim.modes/role_modes "
            "unit_power_mw_mp, ppc, vdd, and DVFS metadata for this scenario variant."
        )
    if has_compute_workload and hw_time_max_ms <= 0:
        warnings.append(
            "All compute IP HW time is zero; check ppc, workload size, selected mode, "
            "and DVFS clock metadata for this scenario variant."
        )
    return warnings


def _evidence_id(result: SimRunResult, hash_value: str | None) -> str:
    suffix = hash_value or hashlib.sha256(
        result.model_dump_json().encode("utf-8")
    ).hexdigest()[:16]
    return f"sim-{result.scenario_id}-{_safe(result.variant_id)}-{suffix}"


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in value)
