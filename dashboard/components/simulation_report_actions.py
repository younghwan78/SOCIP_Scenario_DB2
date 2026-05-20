"""HTML report actions for simulation evidence."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_dashboard_contract import REPORT_ACTION_LABELS
from dashboard.components.simulation_api_client import export_simulation_artifacts
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.viewer_api_client import ViewerApiError
from scenario_db.reporting.exporter import build_report_context, generate_report_bundle
from scenario_db.reporting.filenames import artifact_filenames


def report_download_payloads(
    result: dict[str, Any],
    *,
    project_ref: str | None = None,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    soc_ref: str | None = None,
) -> list[dict[str, Any]]:
    context = build_report_context(
        result,
        project_ref=project_ref or _optional_text(result.get("project_ref")),
        scenario_name=scenario_name,
        variant_name=variant_name,
        soc_ref=soc_ref,
    )
    bundle = generate_report_bundle(result, context=context)
    names = artifact_filenames(bundle.prefix)
    return [
        {
            "label": REPORT_ACTION_LABELS[0],
            "file_name": names.timing_chart,
            "mime": "text/html",
            "data": (bundle.timing_chart_html or "").encode("utf-8"),
        },
        {
            "label": REPORT_ACTION_LABELS[1],
            "file_name": names.bw_chart,
            "mime": "text/html",
            "data": (bundle.bw_chart_html or "").encode("utf-8"),
        },
        {
            "label": REPORT_ACTION_LABELS[2],
            "file_name": names.simulation_report,
            "mime": "text/html",
            "data": bundle.simulation_report_html.encode("utf-8"),
        },
    ]


def render_simulation_report_tab(
    result: dict[str, Any],
    *,
    api_base: str | None = None,
    key_prefix: str = "stored",
    project_ref: str | None = None,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    soc_ref: str | None = None,
) -> None:
    try:
        payloads = report_download_payloads(
            result,
            project_ref=project_ref,
            scenario_name=scenario_name,
            variant_name=variant_name,
            soc_ref=soc_ref,
        )
    except Exception as exc:  # pragma: no cover - surfaced in Streamlit instead of failing the page
        st.error(f"Report HTML generation failed: {exc}")
        return

    columns = st.columns(3)
    evidence_id = str(result.get("id") or "simulation-evidence")
    for column, payload in zip(columns, payloads, strict=False):
        column.download_button(
            payload["label"],
            data=payload["data"],
            file_name=payload["file_name"],
            mime=payload["mime"],
            use_container_width=True,
            key=f"{key_prefix}_{evidence_id}_{payload['file_name']}",
        )

    _render_existing_artifacts(result, key_prefix=key_prefix)
    if api_base and evidence_id and not key_prefix.startswith("preview"):
        _render_local_export_action(
            api_base=api_base,
            evidence_id=evidence_id,
            key_prefix=key_prefix,
            project_ref=project_ref or _optional_text(result.get("project_ref")),
            scenario_name=scenario_name,
            variant_name=variant_name,
            soc_ref=soc_ref,
        )


def _render_existing_artifacts(result: dict[str, Any], *, key_prefix: str) -> None:
    artifacts = [item for item in result.get("artifacts") or [] if isinstance(item, dict)]
    if not artifacts:
        return
    st.caption("Stored report artifacts")
    render_copyable_dataframe(
        artifacts,
        key=f"{key_prefix}_report_artifacts",
        use_container_width=True,
        hide_index=True,
    )


def _render_local_export_action(
    *,
    api_base: str,
    evidence_id: str,
    key_prefix: str,
    project_ref: str | None,
    scenario_name: str | None,
    variant_name: str | None,
    soc_ref: str | None,
) -> None:
    output_dir = st.text_input(
        "Local report directory",
        value="",
        placeholder="Server default: output_simulation",
        key=f"{key_prefix}_{evidence_id}_report_output_dir",
    )
    overwrite = st.checkbox(
        "Overwrite existing files",
        value=True,
        key=f"{key_prefix}_{evidence_id}_report_overwrite",
    )
    if not st.button(
        REPORT_ACTION_LABELS[3],
        use_container_width=True,
        key=f"{key_prefix}_{evidence_id}_report_local_export",
    ):
        return
    try:
        response = export_simulation_artifacts(
            api_base,
            evidence_id,
            output_dir=output_dir.strip() or None,
            overwrite=overwrite,
            project_ref=project_ref,
            scenario_name=scenario_name,
            variant_name=variant_name,
            soc_ref=soc_ref,
        )
    except ViewerApiError as exc:
        st.error(str(exc))
        if exc.body:
            st.code(exc.body)
        return
    st.success(f"Saved HTML bundle: {response.get('output_dir')}")
    artifacts = [item for item in response.get("artifacts") or [] if isinstance(item, dict)]
    if artifacts:
        render_copyable_dataframe(
            artifacts,
            key=f"{key_prefix}_{evidence_id}_report_exported_artifacts",
            use_container_width=True,
            hide_index=True,
        )


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
