"""Simulation evidence overlay helpers for viewer responses."""
from __future__ import annotations

from collections import defaultdict
import re
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


def apply_simulation_overlay(view: ViewResponse, evidence) -> ViewResponse:
    """Overlay persisted simulation evidence onto an existing view response."""

    if evidence is None:
        return view
    evidence_id = getattr(evidence, "id", None)
    node_rows = _sim_node_rows(evidence)
    dma_rows = _sim_dma_rows(evidence)

    for node in view.nodes:
        row = _match_node_sim_row(node.data, node_rows)
        if not row:
            continue
        timing = row.get("_timing") or {}
        node.data.sim_overlay = SimOverlay(
            required_clock_mhz=_num(row.get("required_clock_mhz")),
            set_clock_mhz=_num(row.get("set_clock_mhz")),
            set_voltage_mv=_num(row.get("set_voltage_mv")),
            power_mw=_num(row.get("total_power_mw") or row.get("active_power_mw")),
            hw_time_ms=_num(timing.get("hw_time_ms")),
            feasible=bool(row.get("feasible", timing.get("feasible", True))),
            evidence_id=evidence_id,
        )
        _append_sim_node_text(node.data)

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


def _match_node_sim_row(data: NodeData, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    node_text = f"{data.id} {data.label} {data.ip_ref or ''}".lower()
    for row in rows:
        node_id = str(row.get("node_id") or "").lower()
        if node_id and (data.id.lower() == node_id or node_id in node_text):
            return row
    for row in rows:
        ip_ref = str(row.get("ip_ref") or "").lower()
        if ip_ref and data.ip_ref and data.ip_ref.lower() == ip_ref:
            return row
    for row in rows:
        hw_name = str(row.get("hw_name") or "").lower()
        if hw_name and hw_name in node_text:
            return row
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
