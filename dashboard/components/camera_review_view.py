"""Camera review panels using DB Explorer's existing cards and chip styles."""
from __future__ import annotations

from collections import Counter
from html import escape
from typing import Any

import streamlit as st

from dashboard.components.camera_review import (
    BASIC_KPIS,
    REVIEW_GROUPS,
    SEVERITY_EXPLANATION,
    SEVERITY_LABELS,
    SLOW_KPIS,
    coverage,
    evidence_notes,
    is_camera,
    kpi_label,
    review_groups,
    review_sort_key,
    scenario_variants,
    scenario_intro,
    workload_factors,
)
from dashboard.components.explorer_api_client import viewer_link

Item = dict[str, Any]


def badge(label: str, tone: str = "neutral") -> str:
    colors = {
        "neutral": ("#F3F4F6", "#E5E7EB", "#4B5563"),
        "light": ("#F0FDF4", "#BBF7D0", "#14532D"),
        "medium": ("#FEFCE8", "#FDE68A", "#713F12"),
        "heavy": ("#FFF7ED", "#FED7AA", "#7C2D12"),
        "critical": ("#FEF2F2", "#FECACA", "#7F1D1D"),
        "registered": ("#E8F1EF", "#BBD5CF", "#174D47"),
    }
    bg, border, fg = colors.get(tone, colors["neutral"])
    return f'<span class="tag-chip" style="--chip-bg:{bg};--chip-border:{border};--chip-fg:{fg}">{escape(label)}</span>'


def _cards(cards: list[str]) -> None:
    st.markdown(f'<div class="catalog-card-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _kpi_cards(items: list[Item], group: str, kpis: tuple[str, ...]) -> None:
    cards = []
    for kpi, count in coverage(items, group, kpis).items():
        state = f"등록 {count}개" if count else "현재 범위에서 미확인"
        cards.append(
            f'<div class="matrix-summary-card"><div class="catalog-card-title">{kpi}</div>'
            f'{badge(state, "registered" if count else "neutral")}</div>'
        )
    st.markdown(f'<div class="matrix-summary-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_camera_overview(items: list[Item], catalog: list[Item], *, partial: bool) -> None:
    camera = [item for item in items if is_camera(item)]
    st.markdown("### Camera 검토 현황")
    st.caption("현재 SoC / 과제 / 시나리오 / Load 필터 범위입니다. 등록 수는 성능 검증 완료를 뜻하지 않습니다.")
    if partial:
        st.warning("API 결과 일부만 표시 중입니다. 미확인 항목을 미등록으로 판단하지 말고 과제나 시나리오를 좁혀 확인하세요.")
    st.markdown("**1. 기본 녹화 KPI부터 확인하세요**")
    st.caption("일반 녹화 조건의 커버리지입니다. Portrait / Dual / Pro / 고속 촬영은 별도로 검토합니다.")
    _kpi_cards(camera, "recording", BASIC_KPIS)
    st.markdown("**2. 부하가 커지는 이유에 따라 확장 모드를 확인하세요**")
    cards = []
    for key in ("slow", "portrait", "dual", "pro"):
        guide = REVIEW_GROUPS[key]
        count = sum(key in review_groups(item) for item in camera)
        cards.append(
            f'<div class="catalog-card"><div class="catalog-card-title">{escape(guide["title"])}</div>'
            f'{badge(guide["badge"])}{badge(f"등록 {count}개" if count else "현재 범위에서 미확인", "registered" if count else "neutral")}'
            f'<div class="catalog-card-kv">{escape(guide["why"])}</div>'
            f'<div class="catalog-card-kv"><b>검토 초점</b> · {escape(guide["focus"])}</div></div>'
        )
    _cards(cards)
    st.caption("Variant Matrix에서 검토 목적 → KPI → variant를 선택하면 조건과 부하 요인을 확인할 수 있습니다. 복합 모드는 여러 검토 그룹에 포함됩니다.")
    with st.expander("과제별 기본 KPI 등록 범위 / 조건 확인", expanded=False):
        project_ids = sorted({str(item.get("project_id")) for item in catalog if is_camera(item)})
        rows = []
        for project in project_ids:
            scoped = [item for item in camera if str(item.get("project_id")) == project]
            counts = coverage(scoped, "recording", BASIC_KPIS)
            rows.append({"과제": project, **{k: f"{v}개" if v else "미확인" for k, v in counts.items()}})
        st.dataframe(rows, hide_index=True, use_container_width=True)
        unknown = sum(kpi_label(item) == "KPI 조건 미상" for item in camera if "other" not in review_groups(item))
        st.caption(f"녹화 계열 중 해상도 / fps 조건 미상: {unknown}개. 이름만으로 KPI 값을 채우지 않습니다.")


def render_severity_guide() -> None:
    st.markdown("**Severity · 부하 등급 읽기**")
    st.markdown("".join(badge(f"{key} · {label}", key) for key, label in SEVERITY_LABELS.items()), unsafe_allow_html=True)
    st.caption(SEVERITY_EXPLANATION)


def catalog_camera_summary(scenario: Item, items: list[Item]) -> str:
    if not is_camera(scenario):
        return ""
    variants = scenario_variants(scenario, items)
    groups = Counter(group for item in variants for group in review_groups(item))
    descriptions = []
    for group, guide in REVIEW_GROUPS.items():
        if groups[group]:
            descriptions.append(badge(f'{guide["title"]} {groups[group]}'))
    if not descriptions:
        return '<div class="catalog-card-kv">현재 범위에서 variant 조건을 확인할 수 없습니다.</div>'
    purpose = " / ".join(REVIEW_GROUPS[key]["focus"] for key in groups if key != "other")
    if not purpose:
        purpose = REVIEW_GROUPS["other"]["focus"]
    return (
        f'<div class="catalog-card-kv">{escape(scenario_intro(scenario))}</div>'
        f'<div class="catalog-card-kv">{"".join(descriptions)}</div>'
        f'<div class="catalog-card-kv"><b>검토 초점</b> · {escape(purpose)}</div>'
    )


def _variant_label(item: Item) -> str:
    design = item.get("design_conditions") or {}
    additions = " · ".join(f"{key}={design[key]}" for key in ("hdr", "stabilization", "camera_mode") if key in design)
    return f'{kpi_label(item)} · {item.get("severity") or "등급 미상"} · {item.get("variant_id")} · {item.get("project_id")} / {item.get("scenario_name")} {additions}'


def render_variant_detail(item: Item) -> None:
    severity = str(item.get("severity") or "unknown").lower()
    badges = badge(kpi_label(item), "registered") + badge(f"저장 등급: {severity}", severity)
    badges += "".join(badge(REVIEW_GROUPS[group]["badge"]) for group in review_groups(item))
    st.markdown(badges, unsafe_allow_html=True)
    st.caption(f'{item.get("project_id")} / {item.get("scenario_id")} / {item.get("variant_id")}')
    left, right = st.columns(2)
    with left:
        st.markdown("**왜 검토하나요?**")
        for group in review_groups(item):
            st.write(REVIEW_GROUPS[group]["why"])
        notes = evidence_notes(item)
        if notes:
            st.markdown("".join(badge(note, "medium") for note in notes), unsafe_allow_html=True)
        st.caption("등록된 조건의 검토 안내입니다. 처리 가능 여부와 실측 결과는 별도 확인이 필요합니다.")
    with right:
        st.markdown("**이 variant의 부하 검토 요인**")
        factors = "".join(
            f'<div class="catalog-card-kv"><b>{escape(label)}</b> · {escape(detail)}</div>'
            for label, detail in workload_factors(item)
        )
        st.markdown(f'<div class="help-card">{factors}</div>', unsafe_allow_html=True)
    st.caption(f"왜 {severity}인가요? 등급 지정 사유 / 임계값은 현재 데이터에 제공되지 않습니다. 위 등록 조건을 근거로 과제 담당자의 분류 기준과 대조하세요.")
    st.link_button("이 조건을 Pipeline Viewer에서 확인", viewer_link(item.get("viewer_query") or {}))
    with st.expander("등록된 전체 조건 / 태그", expanded=False):
        st.json({"design_conditions": item.get("design_conditions") or {}, "tags": item.get("tags") or []})


def render_catalog_load_detail(items: list[Item]) -> None:
    camera = sorted([item for item in items if is_camera(item)], key=review_sort_key)
    if not camera:
        return
    with st.expander("등급별 실제 variant와 부하 요인 확인", expanded=False):
        grades = sorted({str(item.get("severity") or "unknown") for item in camera})
        grade = st.selectbox("저장된 등급", ["전체", *grades], key="camera_catalog_grade")
        matching = [item for item in camera if grade == "전체" or str(item.get("severity") or "unknown") == grade]
        # Use full ownership keys so the same variant ID in another scenario cannot collide.
        choices = {(str(item.get("project_id")), str(item.get("scenario_id")), str(item.get("variant_id"))): item for item in matching}
        selected = st.selectbox("등급을 살펴볼 variant", list(choices), format_func=lambda key: _variant_label(choices[key]), key="camera_catalog_variant")
        if selected is not None:
            render_variant_detail(choices[selected])


def render_camera_matrix(items: list[Item]) -> list[Item]:
    st.markdown("**검토 목적을 선택하세요**")
    counts = Counter(group for item in items for group in review_groups(item))
    group = st.pills(
        "Camera 검토 그룹", ["all", *REVIEW_GROUPS], default="all",
        format_func=lambda key: f"전체 ({len(items)})" if key == "all" else f'{REVIEW_GROUPS[key]["title"]} ({counts[key]})',
        key="camera_matrix_group",
    ) or "all"
    matching = sorted([item for item in items if group == "all" or group in review_groups(item)], key=review_sort_key)
    if group != "all":
        guide = REVIEW_GROUPS[group]
        st.markdown(f'<div class="help-card"><b>{escape(guide["why"])}</b><br>검토 초점 · {escape(guide["focus"])}</div>', unsafe_allow_html=True)
    kpis = BASIC_KPIS if group == "recording" else SLOW_KPIS if group == "slow" else ()
    if kpis:
        _kpi_cards(matching, group, kpis)
    available = list(dict.fromkeys([*kpis, *(kpi_label(item) for item in matching)]))
    kpi = st.selectbox("KPI로 좁히기", ["전체 KPI", *available], key=f"camera_matrix_kpi_{group}")
    if kpi != "전체 KPI":
        matching = [item for item in matching if kpi_label(item) == kpi]
    if not matching:
        st.info("현재 필터에서 해당 조건이 확인되지 않습니다. 과제 / 시나리오 / Load 필터를 확인하고 필요한 모드의 등록 조건을 검토하세요.")
        return []
    choices = {(str(item.get("project_id")), str(item.get("scenario_id")), str(item.get("variant_id"))): item for item in matching}
    selected = st.selectbox("검토할 variant · KPI / 등급 / 조건", list(choices), format_func=lambda key: _variant_label(choices[key]), key=f"camera_matrix_variant_{group}")
    if selected is not None:
        render_variant_detail(choices[selected])
    st.caption(f"아래 표도 선택한 검토 그룹과 KPI에 맞춰 {len(matching)}개 variant를 표시합니다.")
    return matching
