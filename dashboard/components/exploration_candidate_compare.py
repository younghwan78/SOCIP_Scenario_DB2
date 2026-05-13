from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_actions import rounded_number
from dashboard.components.table_actions import render_copyable_dataframe


COMPARISON_PRIORITY = [
    "case_id",
    "variant_id",
    "feasible",
    "warning_count",
    "total_power_mw",
    "delta_total_power_mw",
    "core_power_mw",
    "delta_core_power_mw",
    "bw_power_mw",
    "delta_bw_power_mw",
    "total_bw_mbs",
    "delta_total_bw_mbs",
    "hw_time_max_ms",
    "delta_hw_time_max_ms",
    "timeline_end_ms",
    "delta_timeline_end_ms",
    "infeasible_reason",
]


def comparison_rows(preview: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in preview.get("comparison") or []:
        if not isinstance(item, dict):
            continue
        row = {key: _format_value(item.get(key)) for key in COMPARISON_PRIORITY if key in item}
        for key, value in item.items():
            if key not in row:
                row[key] = _format_value(value)
        rows.append(row)
    return rows


def candidate_ids(preview: dict[str, Any]) -> list[str]:
    ids = []
    for case in preview.get("cases") or []:
        if isinstance(case, dict) and case.get("case_id"):
            ids.append(str(case["case_id"]))
    return ids


def selected_candidate(preview: dict[str, Any], case_id: str | None) -> dict[str, Any] | None:
    cases = [case for case in preview.get("cases") or [] if isinstance(case, dict)]
    if not cases:
        return None
    if case_id:
        for case in cases:
            if str(case.get("case_id")) == case_id:
                return case
    return cases[0]


def render_candidate_comparison(preview: dict[str, Any], *, key_prefix: str) -> str | None:
    rows = comparison_rows(preview)
    if not rows:
        st.info("No preview candidates are available. Run Preview Set after compiling a sweep.")
        return None
    render_copyable_dataframe(rows, key=f"{key_prefix}_candidate_comparison", use_container_width=True, hide_index=True)
    ids = candidate_ids(preview)
    if not ids:
        return None
    selected_key = f"{key_prefix}_selected_case"
    if st.session_state.get(selected_key) not in ids:
        st.session_state[selected_key] = ids[0]
    return st.selectbox("Selected candidate", ids, key=selected_key)


def _format_value(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return rounded_number(value)
    return value
