"""Variant condition comparison: reference selection, pivot matrix and A/B diff.

Pure helpers are kept free of Streamlit so they can be unit tested; the
render_* functions add the interactive layer used by DB Explorer and the
Variant Compare page.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

PRIORITY_KEYS = (
    "resolution", "fps", "hdr", "stabilization", "camera_mode", "sensor_place", "sensor_places",
    "codec_mfc", "record_bitrate_mbps", "mcsc_dma_channels", "dpu_layer_count", "extend_mode",
    "portrait", "power_saving_mode", "sensor_input_fps", "sensor_bitwidth", "subscenario",
    "is_scenario", "dvfs_sn",
)
SOURCE_SUFFIXES = ("_source",)
MISSING = "—"


def value_text(value: Any) -> str:
    if value is None:
        return MISSING
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _conditions(item: Mapping[str, Any]) -> dict[str, Any]:
    return dict(item.get("design_conditions") or {})


def is_source_key(key: str) -> bool:
    return key.endswith(SOURCE_SUFFIXES)


def condition_distance(a: Mapping[str, Any], b: Mapping[str, Any]) -> int:
    ca, cb = _conditions(a), _conditions(b)
    keys = {key for key in set(ca) | set(cb) if not is_source_key(key)}
    return sum(1 for key in keys if value_text(ca.get(key)) != value_text(cb.get(key)))


def medoid_variant_id(group: list[Mapping[str, Any]]) -> str:
    """Variant closest to all others: a natural comparison baseline."""
    base = [item for item in group if not item.get("derived_from_variant")] or group
    if not base:
        return ""
    scored = sorted(
        (sum(condition_distance(item, other) for other in base), str(item.get("variant_id")))
        for item in base
    )
    return scored[0][1]


def group_by_scenario(items: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in items:
        groups.setdefault((str(item.get("project_id")), str(item.get("scenario_id"))), []).append(item)
    return groups


def ordered_keys(keys: Iterable[str]) -> list[str]:
    keys = set(keys)
    head = [key for key in PRIORITY_KEYS if key in keys]
    return head + sorted(keys - set(head))


def differing_keys(group: list[Mapping[str, Any]]) -> tuple[list[str], dict[str, str]]:
    """Keys whose value varies across the group, and the constant ones."""
    all_keys = {key for item in group for key in _conditions(item) if not is_source_key(key)}
    varying, constant = [], {}
    for key in all_keys:
        values = {value_text(_conditions(item).get(key)) for item in group}
        if len(values) > 1:
            varying.append(key)
        else:
            constant[key] = next(iter(values))
    return ordered_keys(varying), {key: constant[key] for key in ordered_keys(constant)}


def assumed_keys(item: Mapping[str, Any]) -> list[str]:
    conditions = _conditions(item)
    out = []
    for key, value in conditions.items():
        if is_source_key(key) and str(value).lower().startswith("assumed"):
            out.append(key[: -len("_source")])
    return sorted(out)


def pivot_rows(
    group: list[Mapping[str, Any]],
    reference_id: str,
    keys: list[str],
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """Rows for the pivot table and, per row, the keys that differ from the reference.

    Derived variants are compared to their parent when the parent is in the group,
    so exploration/timing overlays show only what they actually override.
    """
    by_id = {str(item.get("variant_id")): item for item in group}
    reference = by_id.get(reference_id) or (group[0] if group else {})
    rows, changed = [], []
    for item in sorted(group, key=lambda entry: (str(entry.get("variant_id")) != reference_id, str(entry.get("variant_id")))):
        parent_id = str(item.get("derived_from_variant") or "")
        baseline = by_id.get(parent_id) if parent_id in by_id else reference
        conditions, base = _conditions(item), _conditions(baseline)
        diff_keys = [key for key in keys if value_text(conditions.get(key)) != value_text(base.get(key))]
        own = set(item.get("own_condition_keys") or [])
        if parent_id:
            diff_keys = [key for key in diff_keys if not own or key in own]
        row: dict[str, Any] = {
            "variant": str(item.get("variant_id")),
            "기준": "★" if str(item.get("variant_id")) == reference_id else "",
            "Δ": 0 if str(item.get("variant_id")) == reference_id else len(diff_keys),
            "vs": "" if str(item.get("variant_id")) == reference_id else (parent_id if parent_id in by_id else reference_id),
            "load": item.get("severity") or "",
        }
        for key in keys:
            row[key] = value_text(conditions.get(key))
        row["assumed"] = ", ".join(assumed_keys(item))
        rows.append(row)
        changed.append([] if str(item.get("variant_id")) == reference_id else diff_keys)
    return rows, changed


def condition_diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[dict[str, str]]:
    ca, cb = _conditions(a), _conditions(b)
    rows = []
    for key in ordered_keys(set(ca) | set(cb)):
        va, vb = value_text(ca.get(key)), value_text(cb.get(key))
        if key not in cb:
            status = "A only"
        elif key not in ca:
            status = "B only"
        elif va != vb:
            status = "changed"
        else:
            status = "same"
        rows.append({"key": key, "A": va, "B": vb, "status": status})
    order = {"changed": 0, "A only": 1, "B only": 1, "same": 2}
    return sorted(rows, key=lambda row: order[row["status"]])


# ---------------------------------------------------------------------------
# Streamlit rendering
# ---------------------------------------------------------------------------

def _style_pivot(df, changed: list[list[str]]):
    def highlight(row):
        keys = set(changed[row.name]) if row.name < len(changed) else set()
        return [
            "background-color:#FEF3C7;color:#78350F;font-weight:700" if column in keys else
            ("color:#9CA3AF" if row.get(column) == MISSING else "")
            for column in row.index
        ]
    return df.style.apply(highlight, axis=1)


def render_variant_pivot(items: list[Mapping[str, Any]], *, key_prefix: str, page_url_for=None) -> list[str]:
    """Render reference-based pivot for one scenario; returns selected variant ids."""
    import pandas as pd
    import streamlit as st

    st.markdown("**Key conditions · 조건 차이 비교**")
    groups = group_by_scenario(items)
    if not groups:
        st.info("현재 범위에 비교할 variant가 없습니다.")
        return []
    owners = sorted(groups, key=lambda owner: (0 if "recording" in owner[1] else 1, owner))
    c1, c2, c3 = st.columns([1.2, 1.4, 0.8])
    with c1:
        owner = st.selectbox("Scenario", owners, format_func=lambda o: f"{o[1]}  ({len(groups[o])})",
                             key=f"{key_prefix}_owner")
    group = list(groups[owner])
    variant_ids = sorted(str(item.get("variant_id")) for item in group)
    medoid = medoid_variant_id(group)
    ref_key = f"{key_prefix}_ref::{owner[1]}"
    if st.session_state.get(ref_key) not in variant_ids:
        st.session_state[ref_key] = medoid
    with c2:
        reference = st.selectbox(
            "기준 variant", variant_ids, key=ref_key,
            format_func=lambda vid: f"{vid}  (대표·자동)" if vid == medoid else vid,
            help="기본값은 다른 variant들과 조건 차이 합이 가장 작은 대표 variant입니다. 파생 variant(derived)는 부모와 비교합니다.",
        )
    with c3:
        search = st.text_input("Variant 검색", key=f"{key_prefix}_search", placeholder="예: uhd30, vdis")
    keys, constant = differing_keys(group)
    shown = [item for item in group if not search or search.lower() in str(item.get("variant_id")).lower()
             or str(item.get("variant_id")) == reference]
    rows, changed = pivot_rows(shown, reference, keys)
    df = pd.DataFrame(rows)
    event = st.dataframe(
        _style_pivot(df, changed), hide_index=True, use_container_width=True,
        height=min(40 + 35 * len(rows), 560), key=f"{key_prefix}_pivot",
        on_select="rerun", selection_mode="multi-row",
        column_config={"Δ": st.column_config.NumberColumn("Δ", help="기준(또는 부모) 대비 다른 조건 수", width="small"),
                       "기준": st.column_config.TextColumn("기준", width="small")},
    )
    selected = [rows[index]["variant"] for index in (getattr(getattr(event, "selection", None), "rows", None) or [])]
    if constant:
        with st.expander(f"공통 조건 {len(constant)}개 (모든 variant 동일)", expanded=False):
            st.markdown(" ".join(f"`{key}={value}`" for key, value in constant.items()))
    st.caption("노란 셀 = 기준(파생 variant는 부모)과 다른 값 · — = 미등록 · assumed = 출처가 assumed인 조건. 행을 1개 선택하면 Pipeline, 2개는 A/B Compare, 3개 이상(최대 8)은 다중 Compare로 이동할 수 있습니다.")
    if page_url_for and selected:
        links = []
        if len(selected) >= 1:
            links.append(f'<a href="{page_url_for("/Pipeline_Viewer", owner, selected[0], None)}" target="_self">Pipeline에서 {selected[0]} 열기</a>')
        if len(selected) == 2:
            links.append(f'<a href="{page_url_for("/Variant_Compare", owner, selected[0], selected[1])}" target="_self">{selected[0]} ↔ {selected[1]} 비교</a>')
        if len(selected) >= 3:
            chosen = selected[:8]
            links.append(f'<a href="{page_url_for("/Variant_Compare", owner, chosen[0], None, variants=",".join(chosen))}" target="_self">{len(chosen)}개 variant 다중 비교</a>')
        st.markdown(" · ".join(links), unsafe_allow_html=True)
    return selected
