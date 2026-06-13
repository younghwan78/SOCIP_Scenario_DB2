"""Preview and saved evidence result panel for the Evidence Dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_actions import (
    render_kpi_metrics,
    render_preview_actions,
    render_result_warnings,
    render_saved_export_actions,
    render_viewer_tab_link,
    result_rows,
)
from dashboard.components.evidence_dashboard_contract import (
    SIMULATION_RESULT_TOP_TABS,
    VIEWER_LINK_LABEL_PREVIEW,
    VIEWER_LINK_LABEL_SAVED,
)
from dashboard.components.evidence_api_client import KIND_MEASUREMENT, KIND_SIMULATION, list_evidence
from dashboard.components.evidence_compare import render_preview_saved_comparison
from dashboard.components.evidence_result_view import render_result_breakdown
from dashboard.components.measurement_result_view import (
    measurement_list_rows,
    prediction_measurement_comparison_rows,
    render_measurement_result,
    sw_task_rows,
)
from dashboard.components.simulation_api_client import list_simulation_results
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.viewer_api_client import ViewerApiError


def render_evidence_results_panel(
    *,
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
) -> None:
    st.subheader("Simulation Results")
    preview_tab, saved_tab = st.tabs(list(SIMULATION_RESULT_TOP_TABS))
    with preview_tab:
        _render_preview_result(api_base, scenario_id, variant_id, soc_id, project_id)
    with saved_tab:
        _render_saved_results(api_base, scenario_id, variant_id, soc_id, project_id)


def render_measurement_results_panel(
    *,
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
    method: str,
) -> None:
    """List + inspect measurement (or projection) evidence for the selection."""
    is_projection = method == "Projection"
    st.subheader("Projection Evidence" if is_projection else "Measurement Evidence")

    measurement_items, measurement_error = _load_evidence_list(
        api_base,
        KIND_MEASUREMENT,
        scenario_id,
        variant_id,
        project_id,
    )
    prediction_items, prediction_error = _load_evidence_list(
        api_base,
        KIND_SIMULATION,
        scenario_id,
        variant_id,
        project_id,
    )
    fallback_notes: list[str] = []
    if project_id and not measurement_items and not measurement_error:
        fallback_measurements, fallback_error = _load_evidence_list(
            api_base,
            KIND_MEASUREMENT,
            scenario_id,
            variant_id,
            None,
        )
        if not fallback_error:
            measurement_items = _unscoped_evidence_items(fallback_measurements)
            if measurement_items:
                fallback_notes.append("Using legacy evidence without project_ref for measurement rows.")
    if project_id and not prediction_items and not prediction_error:
        fallback_predictions, fallback_error = _load_evidence_list(
            api_base,
            KIND_SIMULATION,
            scenario_id,
            variant_id,
            None,
        )
        if not fallback_error:
            prediction_items = _unscoped_evidence_items(fallback_predictions)
            if prediction_items:
                fallback_notes.append("Using legacy evidence without project_ref for prediction rows.")
    projection_items = [ev for ev in prediction_items if _evidence_method(ev) == "projection"]

    items = projection_items if is_projection else measurement_items
    active_error = prediction_error if is_projection else measurement_error
    counterpart_error = measurement_error if is_projection else prediction_error
    if active_error:
        st.error(active_error)
        return
    if not items:
        target = "projection" if is_projection else "measurement"
        st.info(f"No {target} evidence is stored for the selected scenario/variant.")
        return
    for note in fallback_notes:
        st.caption(note)

    rows = measurement_list_rows(items)
    render_copyable_dataframe(rows, key="evidence_meas_list", use_container_width=True, hide_index=True)
    evidence_ids = [str(row["id"]) for row in rows if row.get("id")]
    _ensure_choice("evidence_meas_selected_id", evidence_ids)
    selected_id = st.selectbox("Selected Evidence", evidence_ids, key="evidence_meas_selected_id")
    selected = next((item for item in items if item.get("id") == selected_id), items[0])

    _render_prediction_measurement_comparison(
        selected=selected,
        is_projection=is_projection,
        measurement_items=measurement_items,
        prediction_items=prediction_items,
        counterpart_error=counterpart_error,
    )

    if is_projection:
        # projection is kind=simulation: reuse the sim breakdown, then surface the
        # measured-derived SW timing that the sim view does not render.
        render_result_breakdown(selected, key_prefix="projection", api_base=api_base, project_ref=project_id, soc_ref=soc_id)
        sw_rows = sw_task_rows(selected)
        if sw_rows:
            st.markdown("**SW task timing (projected from source measurement)**")
            render_copyable_dataframe(sw_rows, key="evidence_proj_sw", use_container_width=True, hide_index=True)
    else:
        render_measurement_result(selected, key_prefix="meas")


def clear_evidence_results_cache() -> None:
    _load_sim_results.clear()
    _load_evidence_list.clear()


def _evidence_method(evidence: dict[str, Any]) -> str | None:
    ctx = evidence.get("execution_context")
    return ctx.get("method") if isinstance(ctx, dict) else None


def _unscoped_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("project_ref") in (None, "")]


def _render_prediction_measurement_comparison(
    *,
    selected: dict[str, Any],
    is_projection: bool,
    measurement_items: list[dict[str, Any]],
    prediction_items: list[dict[str, Any]],
    counterpart_error: str | None,
) -> None:
    st.markdown("**Prediction vs Measurement**")
    st.caption("Delta is prediction minus measurement. Positive means the projection is higher than the measured mean.")
    if counterpart_error:
        st.warning(f"Comparison evidence unavailable: {counterpart_error}")
        return

    if is_projection:
        prediction = selected
        measurement = _select_counterpart(
            "Compare with Measurement",
            measurement_items,
            key="evidence_compare_measurement_id",
        )
    else:
        measurement = selected
        prediction = _select_counterpart(
            "Compare with Prediction",
            prediction_items,
            key="evidence_compare_prediction_id",
        )
    if prediction is None or measurement is None:
        missing = "measurement" if is_projection else "prediction"
        st.info(f"No {missing} evidence is available for comparison.")
        return

    st.caption(
        f"Prediction: {prediction.get('id') or '-'} | Measurement: {measurement.get('id') or '-'}"
    )
    rows = prediction_measurement_comparison_rows(prediction=prediction, measurement=measurement)
    if not rows:
        st.info("No overlapping KPI keys between the selected prediction and measurement evidence.")
        return

    _render_comparison_metrics(rows)
    render_copyable_dataframe(rows, key="evidence_prediction_measurement_compare", use_container_width=True, hide_index=True)


def _select_counterpart(label: str, items: list[dict[str, Any]], *, key: str) -> dict[str, Any] | None:
    ids = [str(item.get("id")) for item in items if item.get("id")]
    if not ids:
        return None
    _ensure_choice(key, ids)
    selected_id = st.selectbox(label, ids, key=key)
    return next((item for item in items if str(item.get("id")) == selected_id), items[0])


def _render_comparison_metrics(rows: list[dict[str, Any]]) -> None:
    headline = [
        row
        for row in rows
        if row.get("metric") in ("total_power_mw", "peak_power_mw", "frame_latency_ms", "fps_effective")
    ]
    if not headline:
        headline = rows[:3]
    cols = st.columns(min(4, len(headline)))
    for col, row in zip(cols, headline[:4]):
        delta = row.get("delta_vs_measurement")
        delta_text = f"{delta:+g}" if isinstance(delta, (int, float)) else None
        pct = row.get("delta_pct_vs_measurement")
        if pct:
            delta_text = f"{delta_text} ({pct})" if delta_text else str(pct)
        value = row.get("prediction")
        col.metric(
            str(row.get("metric") or "metric"),
            f"{value:g}" if isinstance(value, (int, float)) else "-",
            delta_text,
        )


@st.cache_data(ttl=20)
def _load_evidence_list(
    base_url: str,
    kind: str,
    scenario_id: str,
    variant_id: str,
    project_id: str | None,
) -> tuple[list[dict], str | None]:
    try:
        return (
            list_evidence(
                base_url,
                kind=kind,
                scenario_ref=scenario_id or None,
                variant_ref=variant_id or None,
                project_ref=project_id or None,
                limit=100,
            ),
            None,
        )
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=20)
def _load_sim_results(
    base_url: str,
    scenario_id: str,
    variant_id: str,
    latest: bool,
) -> tuple[list[dict], str | None]:
    try:
        return (
            list_simulation_results(
                base_url,
                scenario_ref=scenario_id or None,
                variant_ref=variant_id or None,
                latest=latest,
                limit=100,
            ),
            None,
        )
    except ViewerApiError as exc:
        return [], str(exc)


def _render_preview_result(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
) -> None:
    preview_result = st.session_state.get("evidence_preview_result")
    if not isinstance(preview_result, dict):
        st.info("Run a simulation preview from the left panel. Preview results stay separate from saved evidence until confirmed.")
        return

    st.markdown("**Simulation Preview (not saved)**")
    st.caption("Review this preview first. It will not appear in the evidence list until you confirm and save it.")
    preview_kpi = preview_result.get("kpi") if isinstance(preview_result.get("kpi"), dict) else {}
    render_kpi_metrics(preview_kpi)
    render_result_warnings(preview_result)
    render_preview_actions(
        preview_result,
        api_base=api_base,
        preview_payload=st.session_state.get("evidence_preview_payload"),
        on_saved=_after_preview_saved,
    )
    render_viewer_tab_link(
        api_base=api_base,
        scenario_id=scenario_id,
        variant_id=variant_id,
        soc_id=soc_id,
        project_id=project_id,
        evidence_id=None,
        label=VIEWER_LINK_LABEL_PREVIEW,
    )
    render_result_breakdown(
        preview_result,
        key_prefix="preview",
        api_base=api_base,
        project_ref=project_id,
        soc_ref=soc_id,
    )


def _render_saved_results(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
) -> None:
    latest_only = st.toggle("Latest result only", value=False, key="evidence_latest_only")
    results, results_error = _load_sim_results(api_base, scenario_id, variant_id, latest_only)
    if results_error:
        st.error(results_error)
        return
    if not results:
        st.info("No simulation evidence is stored for the selected scenario/variant.")
        return

    rows = result_rows(results)
    render_copyable_dataframe(rows, key="saved_evidence_result_list", use_container_width=True, hide_index=True)
    evidence_ids = [str(row["id"]) for row in rows if row.get("id")]
    _ensure_choice("evidence_selected_evidence_id", evidence_ids)
    selected_id = st.selectbox("Selected Evidence", evidence_ids, key="evidence_selected_evidence_id")
    selected = next((item for item in results if item.get("id") == selected_id), results[0])
    _render_saved_result_detail(api_base, scenario_id, variant_id, soc_id, project_id, selected_id, selected)


def _render_saved_result_detail(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
    selected_id: str,
    selected: dict[str, Any],
) -> None:
    kpi = selected.get("kpi") if isinstance(selected.get("kpi"), dict) else {}
    render_kpi_metrics(kpi)
    render_result_warnings(selected)
    render_viewer_tab_link(
        api_base=api_base,
        scenario_id=scenario_id,
        variant_id=variant_id,
        soc_id=soc_id,
        project_id=project_id,
        evidence_id=selected_id,
        label=VIEWER_LINK_LABEL_SAVED,
    )
    render_saved_export_actions(selected, api_base=api_base, on_deleted=_after_evidence_deleted)
    render_preview_saved_comparison(
        preview=st.session_state.get("evidence_preview_result"),
        saved=selected,
        key_prefix=f"stored_{selected_id}",
    )
    render_result_breakdown(
        selected,
        key_prefix="stored",
        api_base=api_base,
        project_ref=project_id,
        soc_ref=soc_id,
    )


def _after_preview_saved(saved_id: str) -> None:
    clear_evidence_results_cache()
    st.session_state.pop("evidence_preview_result", None)
    st.session_state.pop("evidence_preview_payload", None)
    st.session_state["viewer_sim_mode"] = "specific"
    st.session_state["viewer_sim_evidence_id"] = saved_id
    st.session_state["evidence_selected_evidence_id"] = saved_id


def _after_evidence_deleted(_deleted_id: str) -> None:
    clear_evidence_results_cache()
    st.session_state.pop("evidence_selected_evidence_id", None)


def _ensure_choice(key: str, options: list[str], preferred: str | None = None) -> None:
    if options and st.session_state.get(key) not in options:
        st.session_state[key] = preferred if preferred in options else options[0]
