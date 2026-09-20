"""Category explanations alongside the existing camera review UI."""
from __future__ import annotations

from html import escape

import streamlit as st

from dashboard.components.category_review import (
    CATEGORY_GUIDES,
    DRIVER_REFERENCE,
    PROJECT_CONTEXT,
    Item,
    condition_rows,
    guide_keys,
    is_exynos2600,
    scenario_purpose,
)
from dashboard.components.explorer_api_client import viewer_link


def catalog_category_summary(item: Item) -> str:
    purpose = scenario_purpose(item)
    if not purpose:
        return ""
    return f'<div class="catalog-card-kv"><b>검토 목적</b> · {escape(purpose)}</div>'


def render_project_context(items: list[Item], selected_soc: str | None) -> None:
    if selected_soc == "soc-exynos2600" or any(is_exynos2600(item) for item in items):
        st.info(PROJECT_CONTEXT)


def render_category_overview(
    items: list[Item], catalog: list[Item], *, partial: bool, categories: list[str] | None,
) -> None:
    keys = list(dict.fromkeys(key for item in catalog + items for key in guide_keys(item)))
    if categories:
        keys = list(dict.fromkeys([*(key for key in categories if key in CATEGORY_GUIDES), *keys]))
    if not keys:
        return
    st.markdown("### 카테고리별 검토 안내")
    st.caption("현재 필터의 등록 데이터를 설명합니다. 등록 수와 부하 등급은 성능 검증 완료를 뜻하지 않습니다.")
    if partial:
        st.warning("일부 API 결과만 표시 중입니다. 아래 수치는 현재 수신 범위이며 누락 항목을 미지원으로 판단하지 마세요.")
    for key in keys:
        guide = CATEGORY_GUIDES[key]
        variants = [item for item in items if key in guide_keys(item) or (key == "video" and key in (item.get("category") or []))]
        with st.expander(guide["title"], expanded=categories == [key]):
            st.write(guide["purpose"])
            st.caption(f"현재 응답 범위의 variant {len(variants)}개 · 여러 분류에 속한 항목은 카테고리 간 중복될 수 있습니다.")
            st.markdown("**처리 경로**")
            st.write(guide["flow"])
            st.markdown("**비교 순서와 검토 항목**")
            st.write(guide["review"])
            if any(is_exynos2600(item) for item in catalog + items):
                st.markdown("**Exynos2600 드라이버 모델 해석**")
                st.write(guide["driver"])
    if any(is_exynos2600(item) for item in catalog + items):
        with st.expander("커널 근거 · BW / DVFS / 전력 계산 범위", expanded=False):
            st.markdown(DRIVER_REFERENCE)


def render_category_variant_detail(item: Item) -> None:
    st.write(scenario_purpose(item))
    st.caption(f"{item.get('project_id')} / {item.get('scenario_id')} / {item.get('variant_id')}")
    for key in guide_keys(item):
        guide = CATEGORY_GUIDES[key]
        st.markdown(f"**{guide['title']} · 부하 검토**")
        st.write(guide["review"])
        if is_exynos2600(item):
            st.write(guide["driver"])
    rows = condition_rows(item)
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("등록된 design_conditions가 없습니다. 이름으로 해상도·fps·bitrate를 추정하지 않습니다.")
    st.caption(
        f"저장된 부하 등급: {item.get('severity') or '미상'}. "
        "위 설명은 검토 요인이며 등급 산정식이 아닙니다. 표시되지 않은 조건은 미확인입니다. "
        "실제 활성 IP·버퍼·경로는 Pipeline Viewer에서, 계산 지원·입력·결과 상태는 Driver Models에서 확인하세요."
    )
    st.link_button("이 조건을 Pipeline Viewer에서 확인", viewer_link(item.get("viewer_query") or {}))
    with st.expander("등록 조건 / 태그 원문", expanded=False):
        st.json({"design_conditions": item.get("design_conditions") or {}, "tags": item.get("tags") or []})


def render_category_matrix(items: list[Item]) -> None:
    candidates = [item for item in items if guide_keys(item)]
    if not candidates:
        return
    st.markdown("**카테고리별 실제 variant 조건 해설**")
    choices = {
        (str(item.get("project_id")), str(item.get("scenario_id")), str(item.get("variant_id"))): item
        for item in candidates
    }
    selected = st.selectbox(
        "설명을 살펴볼 variant · 과제 / 시나리오 / variant",
        list(choices),
        format_func=lambda key: " / ".join(key),
        key="category_review_variant",
    )
    if selected is not None:
        render_category_variant_detail(choices[selected])
    st.caption("아래 Variant Matrix 표는 현재 전체 필터 결과를 유지합니다. 위 선택은 상세 설명 대상만 변경합니다.")
