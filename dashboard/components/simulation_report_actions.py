"""HTML report actions for simulation evidence."""
from __future__ import annotations

import hashlib
import io
import json
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st
import streamlit.components.v1 as components

from dashboard.components.evidence_dashboard_contract import REPORT_ACTION_LABELS
from dashboard.components.simulation_api_client import export_simulation_artifacts
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.viewer_api_client import ViewerApiError
from scenario_db.reporting.exporter import build_report_context, generate_report_bundle
from scenario_db.reporting.filenames import artifact_filenames


REPORT_ARTIFACT_TITLES = {
    "simulation_report": "Simulation Report",
    "timing_chart": "Timing Chart",
    "bw_chart": "BW Chart",
}

REPORT_PREVIEW_ORDER = ("simulation_report", "timing_chart", "bw_chart")
REPORT_CACHE_TTL_SECONDS = 300


def report_cache_payload_json(
    result: dict[str, Any],
    *,
    project_ref: str | None = None,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    soc_ref: str | None = None,
) -> str:
    """Build the deterministic cache payload for generated report HTML."""

    payload = {
        "result": result,
        "context": {
            "project_ref": project_ref,
            "scenario_name": scenario_name,
            "variant_name": variant_name,
            "soc_ref": soc_ref,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def report_cache_fingerprint(
    result: dict[str, Any],
    *,
    project_ref: str | None = None,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    soc_ref: str | None = None,
) -> str:
    """Return a stable fingerprint that changes when evidence or report context changes."""

    payload = report_cache_payload_json(
        result,
        project_ref=project_ref,
        scenario_name=scenario_name,
        variant_name=variant_name,
        soc_ref=soc_ref,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        _html_payload(
            artifact_type="timing_chart",
            prefix=bundle.prefix,
            file_name=names.timing_chart,
            html=bundle.timing_chart_html or "",
        ),
        _html_payload(
            artifact_type="bw_chart",
            prefix=bundle.prefix,
            file_name=names.bw_chart,
            html=bundle.bw_chart_html or "",
        ),
        _html_payload(
            artifact_type="simulation_report",
            prefix=bundle.prefix,
            file_name=names.simulation_report,
            html=bundle.simulation_report_html,
        ),
    ]


def report_download_payloads_for_render(
    result: dict[str, Any],
    *,
    project_ref: str | None = None,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    soc_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Return report payloads through a Streamlit cache keyed by the full evidence payload."""

    return _cached_report_download_payloads(
        report_cache_payload_json(
            result,
            project_ref=project_ref,
            scenario_name=scenario_name,
            variant_name=variant_name,
            soc_ref=soc_ref,
        )
    )


@st.cache_data(show_spinner=False, ttl=REPORT_CACHE_TTL_SECONDS)
def _cached_report_download_payloads(cache_payload_json: str) -> list[dict[str, Any]]:
    payload = json.loads(cache_payload_json)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return report_download_payloads(
        result,
        project_ref=_optional_text(context.get("project_ref")),
        scenario_name=_optional_text(context.get("scenario_name")),
        variant_name=_optional_text(context.get("variant_name")),
        soc_ref=_optional_text(context.get("soc_ref")),
    )


def selected_report_payload(payloads: list[dict[str, Any]], artifact_type: str | None) -> dict[str, Any]:
    selected_type = artifact_type or "simulation_report"
    for payload in payloads:
        if payload.get("artifact_type") == selected_type:
            return payload
    raise ValueError(f"Unknown report artifact type: {selected_type}")


def report_zip_payload(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    if not payloads:
        raise ValueError("No report payloads are available")

    prefix = str(payloads[0].get("prefix") or "simulation-report")
    buffer = io.BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for payload in payloads:
            archive.writestr(str(payload["file_name"]), payload.get("data") or b"")

    return {
        "label": REPORT_ACTION_LABELS[1],
        "file_name": f"{prefix}_html_report_bundle.zip",
        "mime": "application/zip",
        "data": buffer.getvalue(),
    }


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
        payloads = report_download_payloads_for_render(
            result,
            project_ref=project_ref,
            scenario_name=scenario_name,
            variant_name=variant_name,
            soc_ref=soc_ref,
        )
    except Exception as exc:  # pragma: no cover - surfaced in Streamlit instead of failing the page
        st.error(f"Report HTML generation failed: {exc}")
        return

    evidence_id = str(result.get("id") or "simulation-evidence")
    selected_type = st.radio(
        "Report artifact",
        options=list(REPORT_PREVIEW_ORDER),
        index=0,
        horizontal=True,
        format_func=lambda value: REPORT_ARTIFACT_TITLES.get(value, str(value)),
        key=f"{key_prefix}_{evidence_id}_report_artifact",
    )
    selected_payload = selected_report_payload(payloads, selected_type)
    zip_payload = report_zip_payload(payloads)

    download_col, zip_col = st.columns(2)
    download_col.download_button(
        REPORT_ACTION_LABELS[0],
        data=selected_payload["data"],
        file_name=selected_payload["file_name"],
        mime=selected_payload["mime"],
        use_container_width=True,
        key=f"{key_prefix}_{evidence_id}_{selected_payload['artifact_type']}_download",
    )
    zip_col.download_button(
        zip_payload["label"],
        data=zip_payload["data"],
        file_name=zip_payload["file_name"],
        mime=zip_payload["mime"],
        use_container_width=True,
        key=f"{key_prefix}_{evidence_id}_report_bundle_zip",
    )

    st.caption(f"Preview: {selected_payload['file_name']}")
    preview_options = report_preview_options(selected_payload, result)
    components.html(
        selected_payload["html"],
        height=preview_options["height"],
        scrolling=preview_options["scrolling"],
    )

    if api_base and evidence_id and not key_prefix.startswith("preview"):
        with st.expander("API server local save", expanded=False):
            st.caption(
                "Writes the HTML bundle on the machine running the API. Use the download buttons above for browser-local files."
            )
            _render_local_export_action(
                api_base=api_base,
                evidence_id=evidence_id,
                key_prefix=key_prefix,
                project_ref=project_ref or _optional_text(result.get("project_ref")),
                scenario_name=scenario_name,
                variant_name=variant_name,
                soc_ref=soc_ref,
            )

    _render_existing_artifacts(result, key_prefix=key_prefix)


def _html_payload(*, artifact_type: str, prefix: str, file_name: str, html: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "title": REPORT_ARTIFACT_TITLES[artifact_type],
        "prefix": prefix,
        "label": REPORT_ACTION_LABELS[0],
        "file_name": file_name,
        "mime": "text/html",
        "html": html,
        "data": html.encode("utf-8"),
    }


def report_preview_options(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    artifact_type = str(payload.get("artifact_type") or "")
    return {
        "height": _preview_height(artifact_type, result),
        "scrolling": artifact_type != "simulation_report",
    }


def _preview_height(artifact_type: str, result: dict[str, Any] | None = None) -> int:
    if artifact_type == "simulation_report":
        row_count = _report_row_count(result or {})
        return max(1600, min(12000, 900 + row_count * 34))
    return 760


def _report_row_count(result: dict[str, Any]) -> int:
    list_rows = sum(
        len([item for item in result.get(key) or [] if isinstance(item, dict)])
        for key in ("external_devices", "dvfs_breakdown", "timing_breakdown", "dma_breakdown", "timeline_events")
    )
    vdd_rows = len(result.get("vdd_power") or {}) if isinstance(result.get("vdd_power"), dict) else 0
    return list_rows + vdd_rows


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
        "API server report directory",
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
        REPORT_ACTION_LABELS[2],
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
