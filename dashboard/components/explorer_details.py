"""Compact Explorer reference dialogs and explicit condition comparisons."""
from __future__ import annotations

import json
from html import escape
from typing import Any
from urllib.parse import quote

import streamlit as st

from dashboard.components.viewer_api_client import ViewerApiError, _request_json

REFERENCE_FIELDS = {
    "sensor": ("sensor_module_ref", "ip-catalogs", "프로젝트의 기본 센서 IP입니다. variant가 선택한 센서는 Pipeline Viewer에서 확인하세요."),
    "display": ("display_module_ref", "ip-catalogs", "프로젝트의 기본 디스플레이 IP입니다. 지원 모드와 variant의 출력 조건을 구분하세요."),
    "sw_profile": ("default_sw_profile_ref", "sw-profiles", "프로젝트의 기본 SW 프로필입니다. 구성요소 버전과 기능 설정을 확인하세요."),
}


def get_reference(api_base: str, kind: str, reference: str) -> dict[str, Any]:
    endpoint = REFERENCE_FIELDS[kind][1]
    return _request_json("GET", api_base, f"/{endpoint}/{quote(reference, safe='')}")


@st.dialog("Scenario Catalog · 참조 상세", width="large")
def reference_dialog(api_base: str, kind: str, reference: str, project: str) -> None:
    st.markdown(f"**{kind}**")
    st.text(f"{project} / {reference}")
    st.caption(REFERENCE_FIELDS[kind][2])
    try:
        data = get_reference(api_base, kind, reference)
    except ViewerApiError as exc:
        st.error(f"상세 정보를 불러오지 못했습니다: {exc}")
        return
    if kind == "sw_profile":
        sections = [("기본 정보", data.get("metadata_") or data.get("metadata")),
                    ("SW 구성요소 / 버전", data.get("components")),
                    ("기능 설정", data.get("feature_flags")),
                    ("호환 조건", data.get("compatibility"))]
    else:
        st.caption(f"분류: {data.get('category') or '미등록'} · RTL: {data.get('rtl_version') or '미등록'}")
        sections = [("지원 기능 / 모드 / 사양", data.get("capabilities")),
                    ("IP 구성", data.get("hierarchy")), ("호환 SoC", data.get("compatible_soc"))]
    with st.container(height=480, border=False):
        for label, value in sections:
            st.markdown(f"**{label}**")
            if value is None or value == {} or value == []:
                st.caption("등록 정보 없음")
            else:
                st.json(value, expanded=1)
        with st.expander("전체 원본"):
            st.json(data)


def render_catalog_references(api_base: str, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    with st.expander("Sensor / Display / SW profile 상세 보기", expanded=False):
        choices = {(str(item.get("project_id")), str(item.get("scenario_id"))): item for item in items}
        selected = st.selectbox("참조를 확인할 시나리오", list(choices),
                                format_func=lambda key: " / ".join(key), key="catalog_reference_scenario")
        if selected is None:
            return
        item = choices[selected]
        for column, (kind, (field, _, _)) in zip(st.columns(3), REFERENCE_FIELDS.items()):
            reference = item.get(field)
            with column:
                st.caption(str(reference or "미등록"))
                if st.button(f"{kind} 상세", key=f"catalog_reference_{kind}", disabled=not reference):
                    reference_dialog(api_base, kind, str(reference), selected[0])


def condition_differences(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare within full ownership scope, using the smallest visible variant ID."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        key = (str(item.get("project_id")), str(item.get("scenario_id")))
        groups.setdefault(key, []).append(item)
    output = []
    for owner, group in groups.items():
        baseline = min(group, key=lambda item: str(item.get("variant_id")))
        base = baseline.get("design_conditions") or {}
        for item in group:
            design = item.get("design_conditions") or {}
            keys = sorted(set(base) | set(design))
            changes = []
            for key in keys:
                changed = (key in base) != (key in design) or json.dumps(base.get(key), sort_keys=True, ensure_ascii=False) != json.dumps(design.get(key), sort_keys=True, ensure_ascii=False)
                value = json.dumps(design[key], ensure_ascii=False, sort_keys=True) if key in design else "미등록"
                changes.append((key, value, changed))
            output.append({"owner": owner, "variant_id": str(item.get("variant_id")),
                           "baseline": str(baseline.get("variant_id")), "conditions": changes})
    return output


def condition_table_html(items: list[dict[str, Any]]) -> str:
    rows = []
    for row in condition_differences(items):
        chips = []
        # Changes come first; every condition remains visible, including removals.
        for key, value, changed in sorted(row["conditions"], key=lambda entry: not entry[2]):
            style = "background:#FEF3C7;color:#78350F;border:1px solid #D97706;font-weight:700;" if changed else "background:#F3F4F6;color:#374151;border:1px solid #E5E7EB;"
            label = ("Δ " if changed else "") + f"{key}={value}"
            chips.append(f'<span style="display:inline-block;margin:3px;padding:3px 6px;border-radius:5px;{style}">{escape(label)}</span>')
        count = sum(changed for _, _, changed in row["conditions"])
        identity = " / ".join((*row["owner"], row["variant_id"]))
        rows.append(f'<tr><td style="padding:8px;vertical-align:top">{escape(identity)}<br><small>기준: {escape(row["baseline"])} · 차이 {count}개</small></td><td style="padding:8px">{"".join(chips) or "등록 조건 없음"}</td></tr>')
    return '<div style="max-height:440px;overflow:auto"><table style="width:100%;font-size:12px"><thead><tr><th>과제 / 시나리오 / variant</th><th>key_conditions · 조건 차이</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'


def render_condition_comparison(items: list[dict[str, Any]]) -> None:
    st.markdown("**Key conditions · 조건 차이 비교**")
    st.caption("같은 과제·시나리오에서 현재 표시된 variant ID 정렬의 첫 항목이 기준입니다. 노란색 Δ는 기준과 다른 값 또는 누락된 조건입니다. 필터를 바꾸면 기준도 달라질 수 있습니다.")
    if items:
        st.markdown(condition_table_html(items), unsafe_allow_html=True)
    else:
        st.info("현재 범위에 비교할 variant가 없습니다.")
