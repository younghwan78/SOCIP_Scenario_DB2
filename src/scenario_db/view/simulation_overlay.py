"""Simulation evidence overlay helpers for viewer responses."""
from __future__ import annotations

from collections import defaultdict
import re
import math
from typing import Any

from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeSimOverlay,
    Level0MetricBreakdown,
    NodeData,
    ResourceMetricSummary,
    SimOverlay,
    ViewResponse,
)
from scenario_db.view.graph_utils import safe_id


def apply_simulation_overlay(view: ViewResponse, evidence) -> ViewResponse:
    """Overlay persisted simulation evidence onto an existing view response."""

    if evidence is None:
        return view
    evidence_id = getattr(evidence, "id", None)
    node_rows = _sim_node_rows(evidence)
    dma_rows = _sim_dma_rows(evidence)
    schedule_rows = _sim_schedule_rows(evidence)

    for node in view.nodes:
        row = _match_node_sim_row(node.data, node_rows)
        schedule = _match_node_schedule(node.data, schedule_rows)
        if not row and not schedule:
            continue
        row = row or {}
        timing = row.get("_timing") or {}
        schedule = schedule or {}
        node.data.sim_overlay = SimOverlay(
            required_clock_mhz=_num(row.get("required_clock_mhz")),
            set_clock_mhz=_num(row.get("set_clock_mhz")),
            set_voltage_mv=_num(row.get("set_voltage_mv")),
            power_mw=_num(row.get("total_power_mw") if row.get("total_power_mw") is not None else row.get("active_power_mw")),
            hw_time_ms=_num(timing.get("hw_time_ms")),
            feasible=bool(row.get("feasible", timing.get("feasible", True))),
            evidence_id=evidence_id,
            start_ms=_num(schedule.get("start_ms")),
            end_ms=_num(schedule.get("end_ms")),
            critical=bool(schedule.get("critical")),
            bottleneck=bool(schedule.get("bottleneck")),
        )
        _append_sim_node_text(node.data)

    _mark_critical_edges(view, getattr(evidence, "timeline_events", None) or [])

    for edge in view.edges:
        rows = _match_edge_dma_rows(edge.data, dma_rows)
        if not rows:
            continue
        bw_mbs = sum(_num(row.get("bw_mbs")) or 0.0 for row in rows)
        bw_power_mw = sum(_num(row.get("bw_power_mw")) or 0.0 for row in rows)
        worst_values = [_num(row.get("bw_mbs_worst")) for row in rows if row.get("bw_mbs_worst") is not None]
        edge.data.sim_overlay = EdgeSimOverlay(
            bw_mbs=bw_mbs,
            bw_power_mw=bw_power_mw,
            bw_mbs_worst=sum(value or 0.0 for value in worst_values) if worst_values else None,
            evidence_id=evidence_id,
        )
        _append_sim_edge_text(edge.data)

    if "simulation" not in view.overlays_available:
        view.overlays_available.append("simulation")
    view.metadata["simulation_evidence_id"] = evidence_id
    _apply_level0_resource_metrics(view, evidence_id, node_rows, dma_rows)
    return view


def _sim_node_rows(evidence) -> list[dict[str, Any]]:
    timing_by_node = {
        str(row.get("node_id")): row
        for row in (getattr(evidence, "timing_breakdown", None) or [])
        if isinstance(row, dict) and row.get("node_id")
    }
    rows: list[dict[str, Any]] = []
    for row in getattr(evidence, "dvfs_breakdown", None) or []:
        if not isinstance(row, dict):
            continue
        merged = dict(row)
        timing = timing_by_node.get(str(row.get("node_id")))
        if timing:
            merged["_timing"] = timing
        rows.append(merged)
    for node_id, timing in timing_by_node.items():
        if not any(str(row.get("node_id")) == node_id for row in rows):
            rows.append({"node_id": node_id, "_timing": timing, **timing})
    return rows


def _sim_dma_rows(evidence) -> list[dict[str, Any]]:
    return [
        row
        for row in (getattr(evidence, "dma_breakdown", None) or [])
        if isinstance(row, dict)
    ]


def _event_node_id(event: dict[str, Any]) -> str:
    node_id = event.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_id
    return re.sub(r"#f[0-9]+$", "", str(event.get("task_id") or ""))


def _nonnegative_index(value: Any) -> int | None:
    number = _num(value)
    if isinstance(value, bool) or number is None or not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _event_frame(event: dict[str, Any]) -> int | None:
    if event.get("frame_index") is not None:
        return _nonnegative_index(event["frame_index"])
    suffix = re.search(r"#f([0-9]+)$", str(event.get("task_id") or ""))
    return int(suffix[1]) if suffix else 0


def _sim_schedule_rows(evidence) -> dict[str, dict[str, Any]]:
    """Frame-0 window per node, with critical/bottleneck flags across frames."""
    rows: dict[str, dict[str, Any]] = {}
    for event in getattr(evidence, "timeline_events", None) or []:
        if not isinstance(event, dict):
            continue
        node_id = _event_node_id(event)
        if not node_id:
            continue
        entry = rows.setdefault(node_id, {"node_id": node_id, "critical": False, "bottleneck": False})
        start, end = _num(event.get("start_ms")), _num(event.get("end_ms"))
        if (_event_frame(event) == 0 and start is not None and end is not None
                and math.isfinite(start) and math.isfinite(end) and end >= start):
            entry["start_ms"] = min(start, entry.get("start_ms", start))
            entry["end_ms"] = max(end, entry.get("end_ms", end))
        entry["critical"] = entry["critical"] or bool(event.get("critical"))
        entry["bottleneck"] = entry["bottleneck"] or bool(event.get("bottleneck"))
    return rows


def _match_node_schedule(data: NodeData, rows: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return _match_node_sim_row(data, [dict(entry, node_id=key) for key, entry in rows.items()])


def _mark_critical_edges(view: ViewResponse, events: list[dict[str, Any]]) -> None:
    """Only mark direct, same-frame, consecutive ranked predecessor links.

    Missing legacy rank/predecessor metadata cannot prove an edge critical.
    Resource dependencies across frames and unrelated critical nodes are not
    pipeline dependencies and must not color a schematic edge.
    """
    by_task: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or not event.get("task_id"):
            continue
        task_id = str(event["task_id"])
        if task_id in by_task:
            duplicates.add(task_id)
        by_task[task_id] = event
    for task_id in duplicates:
        by_task.pop(task_id)
    identities = {node_id: {"node_id": node_id} for event in by_task.values() if (node_id := _event_node_id(event))}
    view_ids: dict[str, list[str]] = defaultdict(list)
    for node in view.nodes:
        match = _match_node_schedule(node.data, identities)
        if match:
            view_ids[match["node_id"]].append(node.data.id)
    pairs: set[tuple[str, str]] = set()
    for target in by_task.values():
        target_rank = _nonnegative_index(target.get("critical_path_rank"))
        frame = _event_frame(target)
        predecessors = target.get("predecessors")
        if not target.get("critical") or target_rank is None or frame is None or not isinstance(predecessors, list):
            continue
        for predecessor in predecessors:
            source = by_task.get(str(predecessor))
            if source is None or not source.get("critical") or _event_frame(source) != frame:
                continue
            source_rank = _nonnegative_index(source.get("critical_path_rank"))
            if source_rank is None or source_rank + 1 != target_rank:
                continue
            pairs.update((a, b) for a in view_ids[_event_node_id(source)] for b in view_ids[_event_node_id(target)] if a != b)
    for edge in view.edges:
        edge.data.critical = edge.data.flow_type != "risk" and (edge.data.source, edge.data.target) in pairs


def _match_node_sim_row(data: NodeData, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Include exact IDs and the explicit Level 1 projection convention in the
    # same uniqueness check. A normalization collision must not choose a row.
    identified = [row for row in rows if row.get("node_id") and (
        data.id.lower() == str(row["node_id"]).lower()
        or data.id == f"ip-{safe_id(str(row['node_id']))}"
    )]
    if identified:
        return identified[0] if len(identified) == 1 else None
    # Legacy evidence without node identity may use an exact, unambiguous
    # catalog/label match. Never attach another identified node's result.
    for key, expected in (("ip_ref", data.ip_ref), ("hw_name", data.label)):
        matches = [row for row in rows if not row.get("node_id") and expected
                   and str(row.get(key) or "").lower() == expected.lower()]
        if len(matches) == 1:
            return matches[0]
    return None


def _match_edge_dma_rows(data: EdgeData, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edge_tokens = _edge_match_tokens(data)
    matched = [
        row
        for row in rows
        if (
            (node_id := str(row.get("node_id") or "").lower())
            and node_id in edge_tokens
        )
        or (
            (hw_name := str(row.get("hw_name") or "").lower())
            and hw_name in edge_tokens
        )
    ]
    if matched:
        return matched
    return []


def _edge_match_tokens(data: EdgeData) -> set[str]:
    tokens: set[str] = set()
    for value in (data.id, data.source, data.target, data.producer, data.consumer, data.buffer_ref):
        if not value:
            continue
        text = str(value).lower()
        tokens.add(text)
        tokens.update(part for part in re.split(r"[^a-z0-9]+", text) if part)
    return tokens


def _apply_level0_resource_metrics(
    view: ViewResponse,
    evidence_id: str | None,
    node_rows: list[dict[str, Any]],
    dma_rows: list[dict[str, Any]],
) -> None:
    overview = view.level0_resource_overview
    if overview is None:
        return

    for row in overview.rows:
        node_row = _match_resource_node_row(row.node_id, row.label, node_rows)
        matched_dma = _match_resource_dma_rows(row.node_id, row.label, row.buffer_refs, dma_rows)
        if not node_row and not matched_dma:
            continue
        timing = (node_row or {}).get("_timing") or {}
        bw_total = sum(_num(item.get("bw_mbs")) or 0.0 for item in matched_dma)
        read_total = _sum_dma_direction(matched_dma, "read")
        write_total = _sum_dma_direction(matched_dma, "write")
        row.metrics = ResourceMetricSummary(
            power_mw=_num((node_row or {}).get("total_power_mw") or (node_row or {}).get("active_power_mw")),
            bw_read_mbs=read_total,
            bw_write_mbs=write_total,
            bw_total_mbs=bw_total if matched_dma else None,
            hw_time_ms=_num(timing.get("hw_time_ms") or (node_row or {}).get("hw_time_ms")),
            evidence_id=evidence_id,
        )

    _refresh_level0_metric_breakdown(overview)


def _match_resource_node_row(node_id: str, label: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    node_text = f"{node_id} {label}".lower()
    for row in rows:
        candidate = str(row.get("node_id") or "").lower()
        if candidate and (candidate == node_id.lower() or candidate in node_text):
            return row
    for row in rows:
        hw_name = str(row.get("hw_name") or "").lower()
        if hw_name and hw_name in node_text:
            return row
    return None


def _match_resource_dma_rows(
    node_id: str,
    label: str,
    buffer_refs: list[str],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = f"{node_id} {label} {' '.join(buffer_refs)}".lower()
    matched = []
    lower_refs = {ref.lower() for ref in buffer_refs}
    for row in rows:
        candidate = str(row.get("node_id") or "").lower()
        hw_name = str(row.get("hw_name") or "").lower()
        buffer_ref = str(row.get("buffer_ref") or row.get("buffer") or "").lower()
        if (candidate and (candidate == node_id.lower() or candidate in text)) or (hw_name and hw_name in text):
            matched.append(row)
            continue
        if buffer_ref and buffer_ref in lower_refs:
            matched.append(row)
    return matched


def _sum_dma_direction(rows: list[dict[str, Any]], direction: str) -> float | None:
    selected = [
        _num(row.get("bw_mbs")) or 0.0
        for row in rows
        if str(row.get("direction") or "").lower() == direction
    ]
    return sum(selected) if selected else None


def _refresh_level0_metric_breakdown(overview) -> None:
    aggregates: dict[str, dict[str, float]] = defaultdict(lambda: {"power": 0.0, "bw": 0.0, "time": 0.0})
    has_value: dict[str, dict[str, bool]] = defaultdict(lambda: {"power": False, "bw": False, "time": False})
    counts: dict[str, int] = defaultdict(int)
    warnings: dict[str, int] = defaultdict(int)
    for row in overview.rows:
        counts[row.subsystem] += 1
        if row.status in {"warning", "blocked"}:
            warnings[row.subsystem] += 1
        if row.metrics is None:
            continue
        if row.metrics.power_mw is not None:
            aggregates[row.subsystem]["power"] += row.metrics.power_mw
            has_value[row.subsystem]["power"] = True
        if row.metrics.bw_total_mbs is not None:
            aggregates[row.subsystem]["bw"] += row.metrics.bw_total_mbs
            has_value[row.subsystem]["bw"] = True
        if row.metrics.hw_time_ms is not None:
            aggregates[row.subsystem]["time"] = max(aggregates[row.subsystem]["time"], row.metrics.hw_time_ms)
            has_value[row.subsystem]["time"] = True

    overview.metric_breakdown = [
        Level0MetricBreakdown(
            subsystem=subsystem,
            power_mw=aggregates[subsystem]["power"] if has_value[subsystem]["power"] else None,
            bw_total_mbs=aggregates[subsystem]["bw"] if has_value[subsystem]["bw"] else None,
            hw_time_ms=aggregates[subsystem]["time"] if has_value[subsystem]["time"] else None,
            node_count=counts[subsystem],
            warning_count=warnings[subsystem],
        )
        for subsystem in sorted(counts)
    ]


def _append_sim_node_text(data: NodeData) -> None:
    overlay = data.sim_overlay
    if overlay is None:
        return
    badges = []
    if overlay.set_clock_mhz is not None:
        badges.append(f"{overlay.set_clock_mhz:.0f}MHz")
    if overlay.power_mw is not None:
        badges.append(f"{overlay.power_mw:.1f}mW")
    if overlay.critical:
        badges.append("CRIT")
    elif overlay.bottleneck:
        badges.append("BTLNK")
    for badge in badges:
        if badge not in data.summary_badges:
            data.summary_badges.append(badge)
    detail = _sim_node_detail(overlay)
    if detail and detail not in data.detail_items:
        data.detail_items.append(detail)


def _append_sim_edge_text(data: EdgeData) -> None:
    overlay = data.sim_overlay
    if overlay is None:
        return
    bits = []
    if overlay.bw_mbs is not None:
        bits.append(f"BW {overlay.bw_mbs:.1f} MB/s")
    if overlay.bw_power_mw is not None:
        bits.append(f"BW power {overlay.bw_power_mw:.1f} mW")
    if overlay.bw_mbs_worst is not None:
        bits.append(f"worst {overlay.bw_mbs_worst:.1f} MB/s")
    detail = "Sim: " + ", ".join(bits) if bits else None
    if detail and detail not in data.detail_items:
        data.detail_items.append(detail)


def _sim_node_detail(overlay: SimOverlay) -> str | None:
    bits = []
    if overlay.required_clock_mhz is not None:
        bits.append(f"req {overlay.required_clock_mhz:.1f}MHz")
    if overlay.set_clock_mhz is not None:
        bits.append(f"set {overlay.set_clock_mhz:.1f}MHz")
    if overlay.set_voltage_mv is not None:
        bits.append(f"{overlay.set_voltage_mv:.0f}mV")
    if overlay.power_mw is not None:
        bits.append(f"{overlay.power_mw:.1f}mW")
    if overlay.hw_time_ms is not None:
        bits.append(f"{overlay.hw_time_ms:.2f}ms")
    if overlay.start_ms is not None and overlay.end_ms is not None:
        bits.append(f"frame 0 t {overlay.start_ms:.2f}-{overlay.end_ms:.2f}ms")
    if overlay.critical:
        bits.append("critical path (any frame)")
    elif overlay.bottleneck:
        bits.append("bottleneck (any frame)")
    if not overlay.feasible:
        bits.append("infeasible")
    return "Sim: " + ", ".join(bits) if bits else None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
