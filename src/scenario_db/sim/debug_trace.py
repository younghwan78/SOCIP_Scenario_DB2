from __future__ import annotations

from typing import Any

from scenario_db.sim.constants import (
    BPP_DEFAULT,
    BPP_MAP,
    REFERENCE_FPS,
    REFERENCE_VOLTAGE_MV,
)
from scenario_db.sim.models import (
    DVFSTable,
    IPTimingResult,
    IPWorkload,
    PortBWResult,
    PortTransferSpec,
    ResolvedIPConfig,
    SimulationInputs,
    TimelineEvent,
)


def build_calculation_trace(
    inputs: SimulationInputs,
    *,
    dvfs_tables: dict[str, DVFSTable],
    resolved: dict[str, ResolvedIPConfig],
    dma_breakdown: list[PortBWResult],
    timing_breakdown: list[IPTimingResult],
    timeline_events: list[TimelineEvent],
    core_power_mw: float,
    bw_power_mw: float,
    total_power_mw: float,
    total_power_ma: float,
    bw_total_mbs: float,
    hw_time_max_ms: float,
    timeline_end_ms: float | None,
    effective_fps: float,
) -> dict[str, Any]:
    """Build a persisted explanation of how simulation numbers were derived."""

    config = inputs.config
    return {
        "schema_version": "1.0",
        "trace_level": config.debug_trace_level,
        "scenario_id": inputs.scenario_id,
        "variant_id": inputs.variant_id,
        "config": {
            "asv_group": config.asv_group,
            "fps": config.fps,
            "effective_fps": effective_fps,
            "sw_margin": config.sw_margin,
            "bw_power_coeff": config.bw_power_coeff,
            "vbat": config.vbat,
            "pmic_efficiency": config.pmic_efficiency,
            "h_blank_margin": config.h_blank_margin,
            "include_timeline": config.include_timeline,
            "timeline_frame_count": config.timeline_frame_count,
            "timeline_frame_period_ms": config.timeline_frame_period_ms,
        },
        "kpi": _kpi_trace(
            core_power_mw=core_power_mw,
            bw_power_mw=bw_power_mw,
            total_power_mw=total_power_mw,
            total_power_ma=total_power_ma,
            bw_total_mbs=bw_total_mbs,
            hw_time_max_ms=hw_time_max_ms,
            timeline_end_ms=timeline_end_ms,
            vbat=config.vbat,
            pmic_efficiency=config.pmic_efficiency,
        ),
        "ip": _ip_traces(
            inputs.workloads,
            resolved=resolved,
            timing_breakdown=timing_breakdown,
            dvfs_tables=dvfs_tables,
            asv_group=config.asv_group,
            h_blank_margin=config.h_blank_margin,
        ),
        "dma": _dma_traces(
            inputs.port_transfers,
            dma_breakdown=dma_breakdown,
            fps=effective_fps,
            bw_power_coeff=config.bw_power_coeff,
            vbat=config.vbat,
            pmic_efficiency=config.pmic_efficiency,
        ),
        "external_devices": list(inputs.external_devices),
        "topology_order": list(inputs.topology_order),
        "timeline": _timeline_trace(inputs.timeline_tasks, inputs.timeline_edges, timeline_events, trace_level=config.debug_trace_level),
        "warnings": list(inputs.warnings),
    }


def _kpi_trace(
    *,
    core_power_mw: float,
    bw_power_mw: float,
    total_power_mw: float,
    total_power_ma: float,
    bw_total_mbs: float,
    hw_time_max_ms: float,
    timeline_end_ms: float | None,
    vbat: float,
    pmic_efficiency: float,
) -> dict[str, Any]:
    return {
        "total_power_mw": {
            "formula": "core_power_mw + bw_power_mw",
            "inputs": {"core_power_mw": core_power_mw, "bw_power_mw": bw_power_mw},
            "result": total_power_mw,
        },
        "total_power_ma": {
            "formula": "total_power_mw / vbat / pmic_efficiency",
            "inputs": {
                "total_power_mw": total_power_mw,
                "vbat": vbat,
                "pmic_efficiency": pmic_efficiency,
            },
            "result": total_power_ma,
        },
        "total_bw_mbs": {
            "formula": "sum(dma[].bw_mbs)",
            "result": bw_total_mbs,
        },
        "hw_time_max_ms": {
            "formula": "max(timing_breakdown[].hw_time_ms)",
            "result": hw_time_max_ms,
        },
        "timeline_end_ms": {
            "formula": "max(timeline_events[].end_ms)",
            "result": timeline_end_ms or 0.0,
        },
    }


def _ip_traces(
    workloads: list[IPWorkload],
    *,
    resolved: dict[str, ResolvedIPConfig],
    timing_breakdown: list[IPTimingResult],
    dvfs_tables: dict[str, DVFSTable],
    asv_group: int,
    h_blank_margin: float,
) -> list[dict[str, Any]]:
    timing_by_node = {item.node_id: item for item in timing_breakdown}
    traces: list[dict[str, Any]] = []
    for workload in workloads:
        config = resolved.get(workload.node_id)
        if config is None:
            continue
        params = workload.sim_params
        usable = max(1e-9, 1.0 - workload.sw_margin)
        initial_required = (
            workload.pixels * workload.fps / usable / params.ppc / 1e6
            if workload.pixels > 0 and workload.fps > 0 and params.ppc > 0
            else 0.0
        )
        manual_clock = workload.manual_clock_mhz or 0.0
        required_before_group = max(initial_required, workload.clock_correction_mhz)
        required_after_manual = max(config.required_clock_mhz, manual_clock)
        timing = timing_by_node.get(workload.node_id)
        table = dvfs_tables.get(config.dvfs_group or "")
        selected_level = table.get_level(config.dvfs_level) if table and config.dvfs_level is not None else None
        traces.append(
            {
                "node_id": workload.node_id,
                "ip_ref": workload.ip_ref,
                "hw_name": workload.hw_name,
                "mode": workload.mode,
                "shape": {
                    "width": workload.width,
                    "height": workload.height,
                    "pixels": workload.pixels,
                    "resolution_mp": workload.pixels / 1e6,
                    "format": workload.format,
                    "fps": workload.fps,
                },
                "required_clock": {
                    "formula": "max(base_required, manual_clock_mhz, clock_correction_mhz), then align by DVFS domain",
                    "inputs": {
                        "pixels": workload.pixels,
                        "fps": workload.fps,
                        "sw_margin": workload.sw_margin,
                        "ppc": params.ppc,
                        "manual_clock_mhz": workload.manual_clock_mhz,
                        "clock_correction_mhz": workload.clock_correction_mhz,
                        "clock_correction_reason": workload.clock_correction_reason,
                    },
                    "base_formula": "pixels * fps / (1 - sw_margin) / ppc / 1e6",
                    "initial_required_mhz": initial_required,
                    "before_group_align_mhz": required_before_group,
                    "manual_clock_mhz": workload.manual_clock_mhz,
                    "after_manual_clock_mhz": required_after_manual,
                    "clock_correction_mhz": workload.clock_correction_mhz,
                    "clock_correction_reason": workload.clock_correction_reason,
                    "sensor_otf_clock_correction_mhz": workload.clock_correction_mhz,
                    "sensor_otf_clock_correction_reason": workload.clock_correction_reason,
                    "after_group_align_mhz": config.required_clock_mhz,
                },
                "dvfs": {
                    "dvfs_group": config.dvfs_group,
                    "asv_group": asv_group,
                    "selection_rule": "minimum DVFS level whose speed_mhz >= required_clock_mhz and voltage exists for ASV group",
                    "required_voltage_rule": "lookup voltage from DVFS table using required_clock_mhz; no formula is applied",
                    "set_voltage_rule": "align to max required_voltage_mv in the shared VDD domain",
                    "candidate_levels": _dvfs_candidates(table, asv_group),
                    "selected_level": config.dvfs_level,
                    "selected_speed_mhz": selected_level.speed_mhz if selected_level else config.set_clock_mhz,
                    "required_voltage_mv": config.required_voltage_mv,
                    "set_clock_mhz": config.set_clock_mhz,
                    "set_voltage_mv": config.set_voltage_mv,
                    "vdd": config.vdd,
                    "vdd_leader": config.vdd_leader,
                    "feasible": config.feasible,
                    "infeasible_reason": config.infeasible_reason,
                },
                "power": {
                    "formula": "unit_power_mw_mp * resolution_mp * (set_voltage_mv / 710)^2 * (fps / 30)",
                    "inputs": {
                        "unit_power_mw_mp": config.unit_power_mw_mp,
                        "resolution_mp": config.input_resolution_mp,
                        "set_voltage_mv": config.set_voltage_mv,
                        "reference_voltage_mv": REFERENCE_VOLTAGE_MV,
                        "fps": config.fps,
                        "reference_fps": REFERENCE_FPS,
                    },
                    "intermediate": {
                        "voltage_scale": (
                            (config.set_voltage_mv / REFERENCE_VOLTAGE_MV) ** 2
                            if config.set_voltage_mv > 0
                            else 0.0
                        ),
                        "fps_scale": config.fps / REFERENCE_FPS if config.fps > 0 else 0.0,
                    },
                    "result_mw": config.total_power_mw,
                },
                "timing": {
                    "formula": "pixels / (set_clock_mhz * 1e6 * ppc) * (1 + h_blank_margin) * 1000",
                    "inputs": {
                        "pixels": workload.pixels,
                        "set_clock_mhz": config.set_clock_mhz,
                        "ppc": params.ppc,
                        "h_blank_margin": h_blank_margin,
                    },
                    "result_ms": timing.hw_time_ms if timing else 0.0,
                    "feasible": timing.feasible if timing else config.feasible,
                    "infeasible_reason": timing.infeasible_reason if timing else config.infeasible_reason,
                },
            }
        )
    return traces


def _dvfs_candidates(table: DVFSTable | None, asv_group: int) -> list[dict[str, Any]]:
    if table is None:
        return []
    return [
        {
            "level": level.level,
            "speed_mhz": level.speed_mhz,
            "voltage_mv": level.voltages.get(asv_group, 0.0),
        }
        for level in table.levels
    ]


def _dma_traces(
    specs: list[PortTransferSpec],
    *,
    dma_breakdown: list[PortBWResult],
    fps: float,
    bw_power_coeff: float,
    vbat: float,
    pmic_efficiency: float,
) -> list[dict[str, Any]]:
    results = {(item.node_id, item.port): item for item in dma_breakdown}
    traces: list[dict[str, Any]] = []
    for spec in specs:
        result = results.get((spec.node_id, spec.port))
        if result is None:
            continue
        effective_fps = float(fps)
        bpp_factor = BPP_MAP.get((spec.format or "").upper(), BPP_DEFAULT)
        comp_ratio = spec.comp_ratio if spec.compression != "disable" else 1.0
        llc_weight = spec.llc_weight if spec.llc_enabled else 1.0
        traces.append(
            {
                "node_id": spec.node_id,
                "ip_ref": spec.ip_ref,
                "hw_name": spec.hw_name,
                "port": spec.port,
                "direction": result.direction,
                "formula": "comp_ratio * fps * width * height * (bitwidth / 8) * format_bpp_factor * r_w_rate / 1e6",
                "bw_formula": "comp_ratio * fps * width * height * (bitwidth / 8) * format_bpp_factor * r_w_rate / 1e6",
                "bw_power_formula": "bw_mbs * bw_power_coeff / 1000 * llc_weight",
                "bw_power_ma_formula": "bw_power_mw / vbat / pmic_efficiency",
                "inputs": {
                    "width": spec.width,
                    "height": spec.height,
                    "fps": effective_fps,
                    "format": spec.format,
                    "bitwidth": spec.bitwidth,
                    "compression": spec.compression,
                    "comp_ratio": comp_ratio,
                    "r_w_rate": spec.r_w_rate,
                    "llc_enabled": spec.llc_enabled,
                    "bw_power_coeff": bw_power_coeff,
                    "vbat": vbat,
                    "pmic_efficiency": pmic_efficiency,
                },
                "intermediate": {
                    "format_bpp_factor": bpp_factor,
                    "llc_weight": llc_weight,
                    "size_mp": result.size_mp,
                },
                "result": {
                    "bw_mbs": result.bw_mbs,
                    "bw_mbs_best": result.bw_mbs_best,
                    "bw_mbs_worst": result.bw_mbs_worst,
                    "bw_power_mw": result.bw_power_mw,
                    "bw_power_ma": result.bw_power_ma,
                },
            }
        )
    return traces


def _timeline_trace(
    tasks: list[dict],
    edges: list[dict],
    events: list[TimelineEvent],
    *,
    trace_level: str = "formula",
) -> dict[str, Any]:
    group_map: dict[str, list[TimelineEvent]] = {}
    for event in events:
        if event.otf_group_id:
            group_map.setdefault(event.otf_group_id, []).append(event)
    cadence_events = [event for event in events if event.cadence_budget_ms is not None]
    wait_events = [
        event
        for event in events
        if (event.resource_wait_ms or 0.0) > 0.0
        or (event.token_wait_ms or 0.0) > 0.0
        or (event.slack_ms is not None and event.slack_ms < 0.0)
        or event.cadence_violation
    ]
    result: dict[str, Any] = {
        "summary": {
            "task_count": len(tasks),
            "edge_count": len(edges),
            "event_count": len(events),
            "otf_group_count": len(group_map),
            "m2m_edge_count": sum(1 for edge in edges if str(edge.get("type") or "").upper() == "M2M"),
            "critical_path_task_count": sum(1 for event in events if event.critical),
            "cadence_event_count": len(cadence_events),
            "cadence_violation_count": sum(1 for event in cadence_events if event.cadence_violation),
            "max_resource_wait_ms": max((event.resource_wait_ms for event in events), default=0.0),
            "max_token_wait_ms": max((event.token_wait_ms for event in events), default=0.0),
        },
        "rules": {
            "otf": "Tasks in the same OTF group are scheduled as a streaming group; the bottleneck task determines group throughput.",
            "m2m": "M2M edges consume producer completion/token availability before the downstream task starts.",
            "resource": "Tasks sharing the same resource_id can wait for that resource.",
            "cadence": "For multi-frame runs, criticality is based on average output cadence across sink/terminal frames rather than first-frame latency.",
        },
        "otf_groups": [
            {
                "group_id": group_id,
                "tasks": [event.task_id for event in group_events],
                "bottleneck_tasks": [event.task_id for event in group_events if event.bottleneck],
                "start_ms": min(event.start_ms for event in group_events),
                "end_ms": max(event.end_ms for event in group_events),
                "span_ms": max(event.end_ms for event in group_events) - min(event.start_ms for event in group_events),
            }
            for group_id, group_events in sorted(group_map.items())
        ],
        "critical_path": [
            _event_trace_row(event)
            for event in sorted(
                (event for event in events if event.critical),
                key=lambda event: event.critical_path_rank if event.critical_path_rank is not None else 10**9,
            )
        ],
        "top_waits": [
            _event_trace_row(event)
            for event in sorted(
                wait_events,
                key=lambda event: (
                    event.cadence_slack_ms if event.cadence_slack_ms is not None else 0.0,
                    -(event.resource_wait_ms or 0.0) - (event.token_wait_ms or 0.0),
                    event.start_ms,
                ),
            )[:10]
        ],
        "cadence": [_event_trace_row(event) for event in cadence_events],
        "edges": [dict(edge) for edge in edges],
    }
    if trace_level == "full":
        result["events"] = [_event_trace_row(event) for event in events]
    return result


def _event_trace_row(event: TimelineEvent) -> dict[str, Any]:
    return {
        "task_id": event.task_id,
        "node_id": event.node_id,
        "hw_name": event.hw_name,
        "task_type": event.task_type,
        "frame_index": event.frame_index,
        "resource_id": event.resource_id,
        "edge_type": event.edge_type,
        "otf_group_id": event.otf_group_id,
        "start_ms": event.start_ms,
        "end_ms": event.end_ms,
        "duration_ms": event.duration_ms,
        "ready_ms": event.ready_ms,
        "resource_wait_ms": event.resource_wait_ms,
        "token_wait_ms": event.token_wait_ms,
        "deadline_ms": event.deadline_ms,
        "slack_ms": event.slack_ms,
        "cadence_interval_ms": event.cadence_interval_ms,
        "cadence_avg_interval_ms": event.cadence_avg_interval_ms,
        "cadence_budget_ms": event.cadence_budget_ms,
        "cadence_slack_ms": event.cadence_slack_ms,
        "cadence_violation": event.cadence_violation,
        "critical": event.critical,
        "critical_path_rank": event.critical_path_rank,
        "bottleneck": event.bottleneck,
        "bottleneck_reason": event.bottleneck_reason,
        "predecessors": list(event.predecessors),
    }
