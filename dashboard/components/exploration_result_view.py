from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_actions import render_kpi_metrics, render_result_warnings
from dashboard.components.evidence_result_view import render_result_breakdown


def candidate_to_result(candidate: dict[str, Any]) -> dict[str, Any]:
    result = candidate.get("result") if isinstance(candidate.get("result"), dict) else {}
    resolved = result.get("resolved") if isinstance(result.get("resolved"), dict) else {}
    kpi = candidate.get("kpi") if isinstance(candidate.get("kpi"), dict) else _kpi_from_result(result)
    return {
        "id": candidate.get("case_id") or result.get("variant_id") or "exploration-preview",
        "schema_version": "2.2",
        "kind": "evidence.simulation.preview",
        "scenario_ref": candidate.get("scenario_id") or result.get("scenario_id"),
        "variant_ref": candidate.get("variant_id") or result.get("variant_id"),
        "overall_feasibility": "production_ready" if candidate.get("feasible", True) else "infeasible",
        "params_hash": "exploration-preview",
        "sweep_context": {
            "case_id": candidate.get("case_id"),
            "axis_values": candidate.get("axis_values") or {},
            "persisted": False,
        },
        "kpi": kpi,
        "warnings": candidate.get("warnings") or result.get("warnings") or [],
        "infeasible_reason": candidate.get("infeasible_reason") or result.get("infeasible_reason"),
        "dvfs_breakdown": list(resolved.values()),
        "dma_breakdown": result.get("dma_breakdown") or [],
        "timing_breakdown": result.get("timing_breakdown") or [],
        "timeline_events": result.get("timeline_events") or [],
        "external_devices": result.get("external_devices") or [],
        "topology_order": result.get("topology_order") or [],
        "vdd_power": result.get("vdd_power") or {},
        "calculation_trace": result.get("calculation_trace"),
        "raw_result": result,
    }


def render_candidate_detail(candidate: dict[str, Any], *, key_prefix: str) -> None:
    result = candidate_to_result(candidate)
    st.markdown("**Selected Candidate Detail**")
    st.caption("Preview detail is not stored as evidence. Download the candidate JSON if it needs separate import/review.")
    render_kpi_metrics(result.get("kpi") if isinstance(result.get("kpi"), dict) else {})
    render_result_warnings(result)
    render_result_breakdown(result, key_prefix=key_prefix)


def _kpi_from_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_power_mw": result.get("total_power_mw"),
        "total_power_ma": result.get("total_power_ma"),
        "core_power_mw": result.get("core_power_mw"),
        "bw_power_mw": result.get("bw_power_mw"),
        "total_bw_mbs": result.get("bw_total_mbs"),
        "hw_time_max_ms": result.get("hw_time_max_ms"),
        "timeline_end_ms": result.get("timeline_end_ms"),
    }
