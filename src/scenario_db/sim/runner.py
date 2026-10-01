from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from scenario_db.models.evidence.common import Aggregation, ExecutionContext, RunInfo
from scenario_db.models.common import SourceType
from scenario_db.models.evidence.measurement import SwTaskTiming
from scenario_db.models.evidence.resolution import (
    OverallFeasibility,
    ResolutionResult,
    ViolationSummary,
)
from scenario_db.models.evidence.simulation import IpBreakdown, SimulationEvidence
from scenario_db.sim.bw_calc import calc_port_bw
from scenario_db.sim.bw_power import BwPowerContext, bw_model_from_config
from scenario_db.sim.cpu_power import CpuPowerModel, profile_cpu_power, sw_task_cpu_power
from scenario_db.sim.debug_trace import build_calculation_trace
from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.models import (
    DVFSTable,
    IPTimingResult,
    PortBWResult,
    PortTransferSpec,
    PortType,
    SimRunResult,
    SimulationInputs,
)
from scenario_db.sim.perf_calc import calc_processing_time_ms
from scenario_db.sim.power_model import resolve_power_model
from scenario_db.sim.power_params import effective_power_params, power_params_lineage
from scenario_db.sim.timeline import build_timeline_events


def run_simulation(
    inputs: SimulationInputs,
    *,
    dvfs_tables: dict[str, DVFSTable] | None = None,
) -> SimRunResult:
    """Run formula simulation and optional SW/HW timeline simulation."""

    dvfs_tables = dvfs_tables or {}
    config = inputs.config
    power_params = effective_power_params(config)
    power_model = resolve_power_model(config.power_model, power_params)
    bw_model = bw_model_from_config(config)
    effective_fps = float(config.fps or 30.0)
    # Mixed-rate pipelines: each port's traffic runs at its owning node's fps
    # (node sim-block override), falling back to the scenario fps.
    fps_by_node = {workload.node_id: workload.fps for workload in inputs.workloads}
    dvfs_resolver = DvfsResolver(
        dvfs_tables,
        asv_group=config.asv_group,
        power_model=power_model,
        clock_basis=config.clock_basis,
        configured_clocks=config.configured_clocks,
        measured_clocks=config.measured_clocks,
        dvfs_policy=config.dvfs_policy,
        promote_tolerance_pct=config.dvfs_promote_tolerance_pct,
    )
    resolved = dvfs_resolver.resolve(
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
            bw_model=bw_model,
        )
        for transfer in [*inputs.port_transfers, *_cpu_bw_transfers(config)]
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
    bw_total_mbs = sum(item.bw_mbs for item in dma_breakdown)
    memory_state: dict | None = None
    if bw_model is None:
        bw_power_mw = sum(item.bw_power_mw for item in dma_breakdown)
    else:
        # Aggregate hook: a MIF-level / residual model may replace the port sum.
        bw_context = BwPowerContext(
            memory_rail=config.memory_rail,
            total_bw_mbs=bw_total_mbs,
            extra={
                "read_mbs": sum(d.bw_mbs for d in dma_breakdown if d.direction == "read"),
                "write_mbs": sum(d.bw_mbs for d in dma_breakdown if d.direction == "write"),
                # DRAM-side traffic: LLC hits never reach the memory controller.
                "dram_mbs": sum(d.bw_mbs * (d.llc_weight if d.llc_enabled and d.llc_weight is not None else 1.0)
                                for d in dma_breakdown),
                "dvfs_sn": inputs.dvfs_sn,
            },
        )
        bw_power_mw = bw_model.aggregate_power_mw(
            [item.bw_power_mw for item in dma_breakdown], context=bw_context)
        mif_state = getattr(bw_model, "mif_state", None)
        if mif_state is not None:
            memory_state = mif_state(bw_context)
    cpu_model = _cpu_power_model(config, power_params)
    cpu_warnings: list[str] = []
    cpu_breakdown: list[dict] = []
    cpu_clusters: dict[str, float] = {}
    cpu_detail: dict | None = None
    if cpu_model is not None:
        period_ms = 1000.0 / effective_fps if effective_fps > 0 else 0.0
        if config.cpu_profile is not None:
            # Measured placement: per task x cluster cycles, frequency residency, gating.
            profiled = profile_cpu_power(config.cpu_profile, model=cpu_model, period_ms=period_ms,
                                         warnings=cpu_warnings)
            cpu_breakdown = profiled["tasks"]
            cpu_clusters = {name: row["total_mw"] for name, row in profiled["clusters"].items()}
            if profiled["dsu"] is not None:
                cpu_clusters[profiled["dsu"]["name"]] = profiled["dsu"]["total_mw"]
            prof = config.cpu_profile
            if prof.variant_ref and (prof.scenario_ref, prof.variant_ref) != (inputs.scenario_id, inputs.variant_id):
                cpu_warnings.append(
                    f"CPU profile {prof.evidence_ref} was measured on {prof.scenario_ref}/{prof.variant_ref}; "
                    "its placement and cycles are applied to this variant as-is."
                )
            cpu_detail = {"source": "pmu_profile", "profile_ref": config.cpu_profile.evidence_ref,
                          "clusters": profiled["clusters"], "dsu": profiled["dsu"]}
        else:
            cpu_breakdown = sw_task_cpu_power(
                inputs.sw_task_timing,
                statistic=inputs.sw_timing_case,
                period_ms=period_ms,
                hw_time_ms={item.node_id: item.hw_time_ms for item in timing_breakdown},
                model=cpu_model,
                warnings=cpu_warnings,
            )
            for row in cpu_breakdown:
                cpu_clusters[row["cluster"]] = cpu_clusters.get(row["cluster"], 0.0) + row["power_mw"]
            cpu_detail = {"source": "sw_timing"}
    cpu_power_mw = sum(cpu_clusters.values())
    total_power_mw = core_power_mw + bw_power_mw + cpu_power_mw
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
    hw_time_max_ms = max((item.hw_time_ms for item in timing_breakdown), default=0.0)
    timeline_end_ms = max((item.end_ms for item in timeline_events), default=None)
    warnings = _simulation_warnings(
        inputs,
        core_power_mw=core_power_mw,
        hw_time_max_ms=hw_time_max_ms,
    )
    warnings.extend(dvfs_resolver.warnings)
    warnings.extend(cpu_warnings)
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
            cpu_power_mw=cpu_power_mw,
        )
        calculation_trace["warnings"] = list(warnings)

    if inputs.driver_model_report is not None:
        calculation_trace = {**(calculation_trace or {}), "driver_models": inputs.driver_model_report}

    return SimRunResult(
        sw_timing_projection=config.sw_timing_projection,
        timing_profile=config.timing_profile,
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
        sw_task_timing=inputs.sw_task_timing,
        external_devices=inputs.external_devices,
        topology_order=inputs.topology_order,
        vdd_power=_vdd_power(
            resolved, dma_breakdown, memory_rail=config.memory_rail, bw_total_mw=bw_power_mw,
            cpu_clusters=cpu_clusters,
            cpu_model=cpu_model,
        ),
        power_breakdown=_power_breakdown(
            resolved,
            dma_breakdown,
            memory_rail=config.memory_rail,
            power_model=power_model,
            bw_total_mw=bw_power_mw,
            bw_model=bw_model,
            power_params=power_params,
            cpu_breakdown=cpu_breakdown,
            cpu_clusters=cpu_clusters,
            cpu_detail=cpu_detail,
            cpu_model=cpu_model,
            memory_state=memory_state,
        ),
        cpu_power_mw=cpu_power_mw,
        cpu_breakdown=cpu_breakdown,
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
    config_profile_ref: str | None = None,
) -> SimulationEvidence:
    """Convert a run result into a persistable SimulationEvidence model."""

    feasibility = (
        OverallFeasibility.production_ready
        if result.feasible
        else OverallFeasibility.infeasible
    )
    assumed = bool(result.sw_timing_projection) or any(row.get("value_source") == "assumed" for row in result.sw_task_timing)
    if result.feasible and assumed:
        feasibility = OverallFeasibility.exploration_only
    critical_events = [event for event in result.timeline_events if event.critical]
    return SimulationEvidence(
        id=evidence_id or _evidence_id(result, params_hash),
        schema_version="2.2",
        kind="evidence.simulation",
        scenario_ref=result.scenario_id,
        variant_ref=result.variant_id,
        project_ref=project_ref,
        derived_from=([result.sw_timing_projection.source_evidence_ref] if result.sw_timing_projection else
                      [result.timing_profile.evidence_ref] if result.timing_profile else []),
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
            source=SourceType.estimated if assumed else SourceType.calculated,
            config_profile_ref=config_profile_ref,
            sw_timing_projection=result.sw_timing_projection.model_dump(mode="json") if result.sw_timing_projection else None,
            timing_profile=result.timing_profile.model_dump(mode="json") if result.timing_profile else None,
        ),
        aggregation=Aggregation(strategy="single_run"),
        kpi={
            "total_power_mw": result.total_power_mw,
            "total_power_ma": result.total_power_ma,
            "core_power_mw": result.core_power_mw,
            "bw_power_mw": result.bw_power_mw,
            **({"cpu_power_mw": result.cpu_power_mw} if result.cpu_breakdown or result.cpu_power_mw else {}),
            "total_bw_mbs": result.bw_total_mbs,
            "hw_time_max_ms": result.hw_time_max_ms,
            "timeline_end_ms": result.timeline_end_ms or 0.0,
            "critical_path_ms": max((event.end_ms for event in critical_events), default=0.0),
            "critical_path_task_count": len(critical_events),
        },
        ip_breakdown=[
            IpBreakdown(
                ip=resolved.ip_ref,
                instance_index=resolved.instance_index,
                power_mW=resolved.total_power_mw,
            )
            for resolved in result.resolved.values()
            if resolved.ip_ref
        ],
        dma_breakdown=result.dma_breakdown,
        timing_breakdown=result.timing_breakdown,
        dvfs_breakdown=list(result.resolved.values()),
        timeline_events=result.timeline_events,
        sw_task_timing=[SwTaskTiming.model_validate(row) for row in result.sw_task_timing],
        external_devices=result.external_devices,
        topology_order=result.topology_order,
        vdd_power=result.vdd_power,
        power_breakdown=result.power_breakdown or None,
        params_hash=params_hash,
        calculation_trace=result.calculation_trace,
    )


def params_hash(inputs: SimulationInputs) -> str:
    payload = inputs.model_dump(mode="json", exclude_none=True)
    # These derived inputs now affect power. Preserve legacy hashes only when
    # the corresponding model is disabled.
    if _cpu_power_model(inputs.config, effective_power_params(inputs.config)) is not None:
        payload["sw_timing_case"] = inputs.sw_timing_case
    bw_model = bw_model_from_config(inputs.config)
    if bw_model is not None and bw_model.model_id == "mif-linear":
        payload["dvfs_sn"] = inputs.dvfs_sn
    if inputs.config.power_model == "v2-vf":
        for raw, workload in zip(payload["workloads"], inputs.workloads):
            raw["clock_constraints"] = [c.model_dump(mode="json") for c in workload.clock_constraints]
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
        if not updated.get("measured_duration") and not float(updated.get("duration_ms") or 0.0):
            updated["duration_ms"] = (
                timing_by_node.get(str(updated.get("node_id")))
                or timing_by_node.get(str(updated.get("id")))
                or timing_by_hw.get(str(updated.get("hw_name")))
                or 0.0
            )
        # Serialized per-frame SW overhead (driver setup / IRQ completion) keeps
        # the IP occupied around its HW run; used by SW timing-margin analysis.
        overhead = float(updated.get("serial_overhead_ms") or 0.0)
        if overhead > 0:
            updated["duration_ms"] = float(updated.get("duration_ms") or 0.0) + overhead
        result.append(updated)
    return result


def _vdd_power(
    resolved: dict[str, object],
    dma_breakdown: list[PortBWResult],
    *,
    memory_rail: str,
    bw_total_mw: float | None = None,
    cpu_clusters: dict[str, float] | None = None,
    cpu_model: CpuPowerModel | None = None,
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
    bw_total = (
        bw_total_mw
        if bw_total_mw is not None
        else sum(dma.bw_power_mw for dma in dma_breakdown)
    )
    if bw_total > 0:
        bucket = grouped.setdefault(
            memory_rail, {"core_mw": 0.0, "bw_mw": 0.0, "total_mw": 0.0}
        )
        bucket["bw_mw"] += bw_total
    # CPU power sits on the cluster's measured rail (topology ``rail``), else "CPU_<CLUSTER>".
    for cluster, mw in (cpu_clusters or {}).items():
        if mw <= 0:
            continue
        rail = cpu_model.rail_for(cluster) if cpu_model is not None else f"CPU_{cluster.upper()}"
        bucket = grouped.setdefault(rail, {"core_mw": 0.0, "bw_mw": 0.0, "total_mw": 0.0})
        bucket["core_mw"] += mw
    for bucket in grouped.values():
        bucket["total_mw"] = bucket["core_mw"] + bucket["bw_mw"]
    return grouped


def _power_breakdown(
    resolved: dict[str, object],
    dma_breakdown: list[PortBWResult],
    *,
    memory_rail: str,
    power_model,
    bw_total_mw: float | None = None,
    bw_model=None,
    power_params=None,
    cpu_breakdown: list[dict] | None = None,
    cpu_clusters: dict[str, float] | None = None,
    cpu_detail: dict | None = None,
    cpu_model: CpuPowerModel | None = None,
    memory_state: dict | None = None,
) -> dict:
    """Three-bucket decomposition aligned with what a bench can measure:
    per-IP core power, memory (BW-driven) power, and CPU/cluster power.
    The cpu bucket holds SW-task CPU power when it is modelled
    (``include_cpu_power`` / power params with a cpu block); otherwise it stays
    empty and the total is the legacy IP + memory sum."""
    ip_by_rail: dict[str, float] = {}
    ip_by_node: dict[str, float] = {}
    for node_id, item in resolved.items():
        power = float(getattr(item, "total_power_mw", 0.0))
        ip_by_node[node_id] = round(power, 6)
        vdd = getattr(item, "vdd", None)
        if vdd:
            ip_by_rail[vdd] = ip_by_rail.get(vdd, 0.0) + power
    ip_total = sum(ip_by_node.values())
    clock_overhead = sum(float(getattr(item, "clock_overhead_mw", 0.0)) for item in resolved.values())
    leakage = sum(float(getattr(item, "leakage_power_mw", 0.0)) for item in resolved.values())
    memory_total = (
        bw_total_mw
        if bw_total_mw is not None
        else sum(dma.bw_power_mw for dma in dma_breakdown)
    )
    cpu_by_cluster = dict(cpu_clusters or {})
    cpu_total = sum(cpu_by_cluster.values())
    cpu_by_task: dict[str, float] = {}
    for row in cpu_breakdown or []:
        cpu_by_task[row["task"]] = cpu_by_task.get(row["task"], 0.0) + row["power_mw"]
    total = ip_total + memory_total + cpu_total
    model_info: dict = {"id": power_model.model_id, "version": power_model.version}
    if bw_model is not None:
        model_info["bw_model"] = bw_model.describe()
    lineage = power_params_lineage(power_params)
    if lineage is not None:
        model_info.update(lineage)
        model_info["ref_voltage_mv"] = getattr(power_model, "ref_voltage_mv", None)
        model_info["ref_fps"] = getattr(power_model, "ref_fps", None)
    if getattr(power_model, "default_clock_power_fraction", None) is not None:
        model_info["default_clock_power_fraction"] = power_model.default_clock_power_fraction
    return {
        "model": model_info,
        "ip": {
            "total_mw": round(ip_total, 6),
            "by_rail": {rail: round(mw, 6) for rail, mw in sorted(ip_by_rail.items())},
            "by_node": ip_by_node,
            **({"clock_overhead_mw": round(clock_overhead, 6)} if clock_overhead else {}),
            **({"leakage_mw": round(leakage, 6)} if leakage else {}),
        },
        "memory": {
            "total_mw": round(memory_total, 6),
            "rail": memory_rail,
            **({"mif": memory_state} if memory_state is not None else {}),
        },
        "cpu": {
            "total_mw": round(cpu_total, 6),
            "by_cluster": {name: round(mw, 6) for name, mw in sorted(cpu_by_cluster.items())},
            # Extra keys only when CPU power is modelled, so legacy evidence keeps its shape.
            **(
                {
                    "by_task": {task: round(mw, 6) for task, mw in sorted(cpu_by_task.items())},
                    "model": cpu_model.describe(),
                    **(cpu_detail or {}),
                }
                if cpu_model is not None
                else {}
            ),
        },
        "total_mw": round(total, 6),
    }


CPU_BW_NODE_PREFIX = "cpu."


def _cpu_bw_transfers(config) -> list[PortTransferSpec]:
    """CPU memory traffic from a measured profile (bus bytes per frame -> MB/s).

    One pseudo DMA port per cluster (``cpu.<cluster>`` / ``BUS``), so CPU BW
    enters the BW total, BW power and the MIF comparison like IP DMA does.
    Bus accesses mix reads and writes; they are booked as reads.
    ``include_cpu_bw`` None = on whenever a CPU profile is given.
    """
    profile = getattr(config, "cpu_profile", None)
    flag = getattr(config, "include_cpu_bw", None)
    if profile is None or flag is False:
        return []
    fps = float(config.fps or 30.0)
    per_cluster: dict[str, float] = {}
    for task in profile.tasks:
        if task.bus_bytes:
            per_cluster[task.cluster] = per_cluster.get(task.cluster, 0.0) + task.bus_bytes
    for name, cluster in profile.clusters.items():
        if name not in per_cluster and cluster.bus_bytes:
            per_cluster[name] = cluster.bus_bytes
    return [
        PortTransferSpec(
            node_id=f"{CPU_BW_NODE_PREFIX}{name}", hw_name="CPU", port="BUS", port_type=PortType.DMA_READ,
            width=0, height=0, bitrate_mbps=bytes_pf * fps * 8 / 1e6,
        )
        for name, bytes_pf in sorted(per_cluster.items()) if bytes_pf > 0
    ]


def _cpu_power_model(config, power_params) -> CpuPowerModel | None:
    """CPU model for the run, or None when SW-task CPU power stays out of the total.

    ``include_cpu_power`` None = auto: included when the resolved
    power_model_params carry a cpu block (coefficients are then data, not code).
    """
    flag = getattr(config, "include_cpu_power", None)
    if flag is None and getattr(config, "cpu_profile", None) is not None:
        flag = True  # a measured CPU profile was asked for explicitly
    has_cpu_params = power_params is not None and (
        bool(power_params.cpu.clusters)
        or any(v is not None for v in (power_params.cpu.default_cluster, power_params.cpu.freq_mhz, power_params.cpu.volt_v))
    )
    if flag is False or (flag is None and not has_cpu_params):
        return None
    return CpuPowerModel.from_params(power_params if has_cpu_params else None)


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
