"""Evidence result actions and summary widgets for the Evidence Dashboard."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from typing import Any

import streamlit as st

from dashboard.components.evidence_dashboard_contract import (
    PREVIEW_ACTION_LABELS,
    SAVED_ACTION_LABELS,
    VIEWER_LINK_LABEL_SAVED,
    build_pipeline_viewer_url,
    warning_severity,
)
from dashboard.components.simulation_api_client import delete_simulation_result, run_simulation
from dashboard.components.viewer_api_client import ViewerApiError


def kpi_value(kpi: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in kpi:
            return kpi[key]
    return None


def rounded_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def render_kpi_metrics(kpi: dict[str, Any]) -> None:
    """Render the common simulation KPI card row."""

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Power", f"{rounded_number(kpi_value(kpi, 'total_power_mw', 'power_mw')) or 0:g} mW")
    c2.metric("Current", f"{rounded_number(kpi_value(kpi, 'total_power_ma', 'power_ma')) or 0:g} mA")
    c3.metric("Bandwidth", f"{rounded_number(kpi_value(kpi, 'total_bw_mbs', 'bw_mbs')) or 0:g} MB/s")
    c4.metric("HW Time", f"{rounded_number(kpi_value(kpi, 'hw_time_max_ms', 'hw_time_ms')) or 0:g} ms")


def result_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in results:
        kpi = item.get("kpi") if isinstance(item.get("kpi"), dict) else {}
        run_info = item.get("run_info") if isinstance(item.get("run_info"), dict) else {}
        rows.append(
            {
                "id": item.get("id"),
                "feasibility": item.get("overall_feasibility"),
                "power_mw": rounded_number(kpi_value(kpi, "total_power_mw", "power_mw")),
                "power_ma": rounded_number(kpi_value(kpi, "total_power_ma", "power_ma")),
                "bw_mbs": rounded_number(kpi_value(kpi, "total_bw_mbs", "bw_mbs")),
                "hw_time_ms": rounded_number(kpi_value(kpi, "hw_time_max_ms", "hw_time_ms")),
                "timeline_end_ms": rounded_number(kpi.get("timeline_end_ms")),
                "timestamp": run_info.get("timestamp"),
                "params_hash": item.get("params_hash"),
            }
        )
    return rows


def render_viewer_tab_link(
    *,
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
    evidence_id: str | None = None,
    label: str = VIEWER_LINK_LABEL_SAVED,
) -> None:
    href = build_pipeline_viewer_url(
        api_base=api_base,
        soc_id=soc_id,
        project_id=project_id,
        scenario_id=scenario_id,
        variant_id=variant_id,
        evidence_id=evidence_id,
    )
    st.markdown(
        f"""
<a class="viewer-tab-link" href="{href}" target="_blank" rel="noopener noreferrer">
  {label}
</a>
""",
        unsafe_allow_html=True,
    )


def render_saved_export_actions(
    result: dict[str, Any],
    *,
    api_base: str,
    on_deleted: Callable[[str], None] | None = None,
) -> None:
    evidence_id = str(result.get("id") or "simulation-evidence")
    filename_base = _safe_filename(evidence_id)
    json_text = evidence_json_text(result)
    col_json, col_kpi, col_dma, col_delete = st.columns(4)
    col_json.download_button(
        SAVED_ACTION_LABELS[1],
        data=json_text.encode("utf-8"),
        file_name=f"{filename_base}.json",
        mime="application/json",
        use_container_width=True,
        key=f"download_json_{evidence_id}",
    )
    col_kpi.download_button(
        SAVED_ACTION_LABELS[2],
        data=summary_csv_bytes(result),
        file_name=f"{filename_base}-summary.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_kpi_{evidence_id}",
    )
    col_dma.download_button(
        SAVED_ACTION_LABELS[3],
        data=rows_csv_bytes(result.get("dma_breakdown") or []),
        file_name=f"{filename_base}-dma.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_dma_{evidence_id}",
    )
    if col_delete.button(SAVED_ACTION_LABELS[4], use_container_width=True, key=f"delete_evidence_{evidence_id}"):
        try:
            delete_simulation_result(api_base, evidence_id)
            if on_deleted:
                on_deleted(evidence_id)
            st.success(f"Deleted evidence: {evidence_id}")
            st.rerun()
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)
    with st.expander("Raw JSON for copy", expanded=False):
        st.code(json_text, language="json")


def render_preview_actions(
    result: dict[str, Any],
    *,
    api_base: str,
    preview_payload: dict[str, Any] | None,
    on_saved: Callable[[str], None] | None = None,
) -> None:
    evidence_id = str(result.get("id") or "simulation-preview")
    filename_base = _safe_filename(evidence_id)
    json_text = evidence_json_text(result)
    col_save, col_json, col_kpi = st.columns(3)
    if col_save.button(PREVIEW_ACTION_LABELS[0], type="primary", use_container_width=True):
        if not isinstance(preview_payload, dict):
            st.error("No preview payload is available to save.")
            return
        try:
            response = run_simulation(api_base, preview_payload)
            saved_id = str(response.get("evidence_id") or evidence_id)
            if on_saved:
                on_saved(saved_id)
            st.success(f"Saved confirmed evidence: {saved_id}")
            st.rerun()
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)
    col_json.download_button(
        PREVIEW_ACTION_LABELS[1],
        data=json_text.encode("utf-8"),
        file_name=f"{filename_base}-preview.json",
        mime="application/json",
        use_container_width=True,
        key=f"download_preview_json_{evidence_id}",
    )
    col_kpi.download_button(
        PREVIEW_ACTION_LABELS[2],
        data=summary_csv_bytes(result),
        file_name=f"{filename_base}-preview-summary.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_preview_kpi_{evidence_id}",
    )
    with st.expander("Preview JSON for copy", expanded=False):
        st.code(json_text, language="json")


def render_result_warnings(result: dict[str, Any]) -> None:
    warnings = result_warnings(result)
    if not warnings:
        return
    message = "\n".join(f"- {warning}" for warning in warnings)
    if warning_severity(warnings) == "error":
        st.error(message)
    else:
        st.warning(message)


def result_warnings(result: dict[str, Any]) -> list[str]:
    direct = result.get("warnings")
    if isinstance(direct, list):
        return [str(item) for item in direct if item]
    trace = result.get("calculation_trace")
    if isinstance(trace, dict) and isinstance(trace.get("warnings"), list):
        return [str(item) for item in trace["warnings"] if item]
    return []


def evidence_json_text(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def summary_csv_bytes(result: dict[str, Any]) -> bytes:
    execution_context = result.get("execution_context") if isinstance(result.get("execution_context"), dict) else {}
    run_info = result.get("run_info") if isinstance(result.get("run_info"), dict) else {}
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    row: dict[str, Any] = {
        "id": result.get("id"),
        "scenario_ref": result.get("scenario_ref"),
        "variant_ref": result.get("variant_ref"),
        "sw_baseline_ref": result.get("sw_baseline_ref"),
        "silicon_rev": execution_context.get("silicon_rev"),
        "thermal": execution_context.get("thermal"),
        "ambient_temp_c": execution_context.get("ambient_temp_c"),
        "overall_feasibility": result.get("overall_feasibility"),
        "params_hash": result.get("params_hash"),
        "timestamp": run_info.get("timestamp"),
    }
    for key, value in kpi.items():
        row[f"kpi_{key}"] = value
    return rows_csv_bytes([row])


def rows_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return b""
    fieldnames: list[str] = []
    for row in clean_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in clean_rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
    return buffer.getvalue().encode("utf-8-sig")


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return value


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]
