"""Sidebar context selection for the Evidence Dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from dashboard.components.simulation_readiness import render_simulation_readiness
from dashboard.components.viewer_api_client import (
    ViewerApiError,
    compact_project_label,
    compact_scenario_label,
    compact_soc_label,
    compact_variant_label,
    default_variant_id,
    list_projects,
    list_scenarios,
    list_soc_platforms,
    list_variants,
)


@dataclass(frozen=True)
class EvidenceContext:
    api_base: str
    soc_id: str
    project_id: str
    scenario_id: str
    variant_id: str


def render_evidence_context_sidebar(
    *,
    default_api_base: str,
    on_refresh: Callable[[], None] | None = None,
) -> EvidenceContext:
    """Render sidebar controls and return the selected simulation context."""

    st.markdown("### Simulation Context")
    api_base = st.text_input("API Base", value=default_api_base, key="evidence_api_base")
    if st.button("Refresh", use_container_width=True):
        clear_evidence_context_caches()
        if on_refresh:
            on_refresh()
        st.rerun()

    scenario_id, variant_id = _select_context(api_base)
    render_simulation_readiness(api_base, scenario_id, variant_id)
    return EvidenceContext(
        api_base=api_base,
        soc_id=str(st.session_state.get("viewer_soc_id") or ""),
        project_id=str(st.session_state.get("viewer_project_id") or ""),
        scenario_id=scenario_id,
        variant_id=variant_id,
    )


def clear_evidence_context_caches() -> None:
    _load_soc_options.clear()
    _load_project_options.clear()
    _load_scenario_options.clear()
    _load_variant_options.clear()


def default_silicon_rev(soc_id: str | None) -> str:
    if "exynos2600" in str(soc_id or "").lower():
        return "EVT1.3"
    return "EVT0"


@st.cache_data(ttl=30)
def _load_soc_options(base_url: str) -> tuple[list[dict], str | None]:
    try:
        return list_soc_platforms(base_url), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_project_options(base_url: str, soc_ref: str | None) -> tuple[list[dict], str | None]:
    try:
        return list_projects(base_url, soc_ref=soc_ref), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_scenario_options(
    base_url: str,
    project_ref: str | None,
    soc_ref: str | None,
) -> tuple[list[dict], str | None]:
    try:
        if project_ref:
            items = list_scenarios(base_url, project_ref=project_ref)
            if items:
                return items, None
        if soc_ref:
            items = list_scenarios(base_url, soc_ref=soc_ref)
            if items:
                return items, None
        return list_scenarios(base_url), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_variant_options(base_url: str, scenario_id: str) -> tuple[list[dict], str | None]:
    try:
        return list_variants(base_url, scenario_id), None
    except ViewerApiError as exc:
        return [], str(exc)


def _select_context(api_base: str) -> tuple[str, str]:
    soc_id = _select_soc(api_base)
    project_id = _select_project(api_base, soc_id)
    scenario_id = _select_scenario(api_base, soc_id, project_id)
    variant_id = _select_variant(api_base, scenario_id)
    return scenario_id, variant_id


def _select_soc(api_base: str) -> str:
    socs, soc_error = _load_soc_options(api_base)
    if socs:
        soc_ids = [str(item.get("id")) for item in socs if item.get("id")]
        _ensure_choice("evidence_soc_id", soc_ids, preferred=st.session_state.get("viewer_soc_id"))
        st.selectbox(
            "SoC Platform",
            soc_ids,
            key="evidence_soc_id",
            on_change=_clear_context_after_soc,
            format_func=lambda value: compact_soc_label(next((item for item in socs if item.get("id") == value), {"id": value})),
        )
        soc_id = st.session_state["evidence_soc_id"]
    else:
        if soc_error:
            st.caption(f"SoC list unavailable: {soc_error}")
        soc_id = st.text_input("SoC Platform", key="evidence_soc_id_text", value=st.session_state.get("viewer_soc_id", ""))
    st.session_state["viewer_soc_id"] = soc_id
    return str(soc_id)


def _select_project(api_base: str, soc_id: str) -> str:
    projects, project_error = _load_project_options(api_base, soc_id or None)
    if projects:
        project_ids = [str(item.get("id")) for item in projects if item.get("id")]
        _ensure_choice("evidence_project_id", project_ids, preferred=st.session_state.get("viewer_project_id"))
        st.selectbox(
            "Project / Board",
            project_ids,
            key="evidence_project_id",
            on_change=_clear_context_after_project,
            format_func=lambda value: compact_project_label(
                next((item for item in projects if item.get("id") == value), {"id": value})
            ),
        )
        project_id = st.session_state["evidence_project_id"]
    else:
        if project_error:
            st.caption(f"Project list unavailable: {project_error}")
        project_id = st.text_input("Project / Board", key="evidence_project_id_text", value=st.session_state.get("viewer_project_id", ""))
    st.session_state["viewer_project_id"] = project_id
    return str(project_id)


def _select_scenario(api_base: str, soc_id: str, project_id: str) -> str:
    scenarios, scenario_error = _load_scenario_options(api_base, project_id or None, soc_id or None)
    if not scenarios:
        if scenario_error:
            st.error(f"Scenario list unavailable: {scenario_error}")
        else:
            st.error("No scenarios are available from the API.")
        st.stop()

    categories = scenario_categories(scenarios)
    _ensure_choice("evidence_scenario_category", categories, preferred=st.session_state.get("evidence_scenario_category", "all"))
    st.pills(
        "Scenario Category",
        categories,
        selection_mode="single",
        key="evidence_scenario_category",
        on_change=_clear_context_after_category,
        format_func=category_label,
        width="stretch",
    )
    category_scenarios = filter_scenarios_by_category(scenarios, st.session_state["evidence_scenario_category"])
    scenario_query = st.text_input("Scenario Search", key="evidence_scenario_filter", placeholder="Filter by id or name")
    filtered_scenarios = filter_scenarios_by_text(category_scenarios, scenario_query)
    if not filtered_scenarios and scenario_query:
        st.warning("No scenarios match the current search filter.")
        filtered_scenarios = category_scenarios

    scenario_ids = [str(item.get("id")) for item in filtered_scenarios if item.get("id")]
    _ensure_choice("evidence_scenario_id", scenario_ids, preferred=st.session_state.get("viewer_scenario_id", "uc-camera-recording"))
    st.selectbox(
        "Scenario",
        scenario_ids,
        key="evidence_scenario_id",
        on_change=_clear_context_after_scenario,
        format_func=lambda value: compact_scenario_label(
            next((item for item in filtered_scenarios if item.get("id") == value), {"id": value})
        ),
    )
    scenario_id = st.session_state["evidence_scenario_id"]
    st.session_state["viewer_scenario_id"] = scenario_id
    return str(scenario_id)


def _select_variant(api_base: str, scenario_id: str) -> str:
    variants, variant_error = _load_variant_options(api_base, scenario_id)
    if not variants:
        if variant_error:
            st.error(f"Variant list unavailable: {variant_error}")
        else:
            st.error("No variants found for this scenario.")
        st.stop()
    variant_ids = [str(item.get("id")) for item in variants if item.get("id")]
    selected_variant = default_variant_id(variants, st.session_state.get("viewer_variant_id", "UHD60-HDR10-H265"))
    _ensure_choice("evidence_variant_id", variant_ids, preferred=selected_variant)
    st.selectbox(
        "Variant",
        variant_ids,
        key="evidence_variant_id",
        on_change=_clear_context_after_variant,
        format_func=lambda value: compact_variant_label(next((item for item in variants if item.get("id") == value), {"id": value})),
    )
    variant_id = st.session_state["evidence_variant_id"]
    st.session_state["viewer_variant_id"] = variant_id
    return str(variant_id)


def _ensure_choice(key: str, options: list[str], *, preferred: str | None = None) -> None:
    if options and st.session_state.get(key) not in options:
        st.session_state[key] = preferred if preferred in options else options[0]


def _clear_context_after_soc() -> None:
    _clear_state(
        "evidence_project_id",
        "evidence_scenario_category",
        "evidence_scenario_id",
        "evidence_variant_id",
        "evidence_selected_evidence_id",
        "evidence_preview_result",
        "evidence_preview_payload",
    )


def _clear_context_after_project() -> None:
    _clear_state(
        "evidence_scenario_category",
        "evidence_scenario_id",
        "evidence_variant_id",
        "evidence_selected_evidence_id",
        "evidence_preview_result",
        "evidence_preview_payload",
    )


def _clear_context_after_category() -> None:
    _clear_state(
        "evidence_scenario_id",
        "evidence_variant_id",
        "evidence_selected_evidence_id",
        "evidence_preview_result",
        "evidence_preview_payload",
    )


def _clear_context_after_scenario() -> None:
    _clear_state("evidence_variant_id", "evidence_selected_evidence_id", "evidence_preview_result", "evidence_preview_payload")


def _clear_context_after_variant() -> None:
    _clear_state("evidence_selected_evidence_id", "evidence_preview_result", "evidence_preview_payload")


def _clear_state(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


def scenario_categories(scenarios: list[dict[str, Any]]) -> list[str]:
    categories = {"all"}
    for item in scenarios:
        metadata = _scenario_metadata(item)
        for key in ("category", "domain"):
            value = metadata.get(key)
            if isinstance(value, list):
                categories.update(str(part) for part in value if part)
            elif value:
                categories.add(str(value))
    return ["all", *sorted(category for category in categories if category != "all")]


def category_label(category: str) -> str:
    if category == "all":
        return "All"
    return category.replace("_", " ").title()


def filter_scenarios_by_category(scenarios: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    if category == "all":
        return scenarios
    filtered = []
    for item in scenarios:
        metadata = _scenario_metadata(item)
        values: list[str] = []
        for key in ("category", "domain"):
            value = metadata.get(key)
            if isinstance(value, list):
                values.extend(str(part) for part in value)
            elif value:
                values.append(str(value))
        if category in values:
            filtered.append(item)
    return filtered


def filter_scenarios_by_text(scenarios: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    needle = str(query or "").strip().lower()
    if not needle:
        return scenarios
    filtered = []
    for item in scenarios:
        metadata = _scenario_metadata(item)
        text = " ".join(
            str(value or "").lower()
            for value in (
                item.get("id"),
                item.get("name"),
                metadata.get("name"),
                metadata.get("title"),
                metadata.get("category"),
                metadata.get("domain"),
            )
        )
        if needle in text:
            filtered.append(item)
    return filtered


def _scenario_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata_") if isinstance(item.get("metadata_"), dict) else item.get("metadata")
    return metadata if isinstance(metadata, dict) else {}
