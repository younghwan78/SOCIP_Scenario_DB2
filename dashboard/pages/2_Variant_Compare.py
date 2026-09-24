r"""Variant Compare: A/B conditions, pipeline structure, evidence KPI and prediction vs measurement.

Run:
  uv run --group dashboard streamlit run dashboard\Home.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scenario_db.api.schemas.view import ViewResponse  # noqa: E402

from dashboard.components.app_context import (  # noqa: E402
    adopt_query_context,
    current_context,
    page_url,
    publish_query,
    render_context_bar,
    set_context,
)
from dashboard.components.compare_views import (  # noqa: E402
    dma_diff,
    domain_chart_rows,
    evidence_kind_label,
    evidence_option_label,
    common_prefix,
    condition_matrix,
    dma_matrix,
    kpi_matrix_wide,
    kpi_side_by_side,
    pm_rows,
    rails_without_domain,
    short_labels,
    unit_diff,
)
from dashboard.components.pipeline_tables import dma_rows  # noqa: E402
from dashboard.components.ui_theme import apply_app_theme, render_page_header  # noqa: E402
from dashboard.components.variant_compare import (  # noqa: E402
    condition_diff,
    differing_keys,
    medoid_variant_id,
)
from dashboard.components.viewer_api_client import (  # noqa: E402
    ViewerApiError,
    _request_json,
    compact_project_label,
    compact_scenario_label,
    compact_soc_label,
    list_projects,
    list_scenarios,
    list_soc_platforms,
    list_variants,
)

st.set_page_config(page_title="Variant Compare - ScenarioDB", page_icon="", layout="wide",
                   initial_sidebar_state="expanded")
apply_app_theme(sidebar_width=288)

STATUS_STYLE = {
    "changed": "background-color:#FEF3C7;color:#78350F;font-weight:700",
    "A only": "background-color:#FEE2E2;color:#7F1D1D",
    "B only": "background-color:#DBEAFE;color:#1E3A8A",
    "same": "color:#9CA3AF",
}


@st.cache_data(ttl=60, show_spinner=False)
def _socs(api_base: str) -> list[dict[str, Any]]:
    return list_soc_platforms(api_base)


@st.cache_data(ttl=60, show_spinner=False)
def _projects(api_base: str, soc_id: str) -> list[dict[str, Any]]:
    return list_projects(api_base, soc_ref=soc_id or None)


@st.cache_data(ttl=60, show_spinner=False)
def _scenarios(api_base: str, project_id: str) -> list[dict[str, Any]]:
    return list_scenarios(api_base, project_ref=project_id or None)


@st.cache_data(ttl=60, show_spinner=False)
def _variants(api_base: str, scenario_id: str) -> list[dict[str, Any]]:
    return list_variants(api_base, scenario_id)


@st.cache_data(ttl=120, show_spinner=False)
def _view(api_base: str, scenario_id: str, variant_id: str) -> dict[str, Any]:
    path = f"/scenarios/{quote(scenario_id, safe='')}/variants/{quote(variant_id, safe='')}/view"
    return ViewResponse.model_validate(_request_json("GET", api_base, path, params={"level": 1})).model_dump(mode="json")


@st.cache_data(ttl=60, show_spinner=False)
def _evidence(api_base: str, scenario_id: str, variant_id: str) -> list[dict[str, Any]]:
    response = _request_json("GET", api_base, "/evidence",
                             params={"scenario_ref": scenario_id, "variant_ref": variant_id, "limit": 100})
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


@st.cache_data(ttl=60, show_spinner=False)
def _pm_compare(api_base: str, prediction_id: str, measurement_id: str) -> dict[str, Any]:
    return _request_json("GET", api_base, "/compare/prediction-measurement",
                         params={"prediction_id": prediction_id, "measurement_id": measurement_id})


def _pick(label: str, options: list[str], preferred: str, key: str, fmt=None) -> str:
    if not options:
        st.selectbox(label, ["(없음)"], key=f"{key}_empty", disabled=True)
        return ""
    if st.session_state.get(key) not in options:
        st.session_state[key] = preferred if preferred in options else options[0]
    return str(st.selectbox(label, options, key=key, format_func=fmt or (lambda value: value)))


def _as_items(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"variant_id": str(item.get("id")), "design_conditions": item.get("design_conditions") or {},
             "derived_from_variant": item.get("derived_from_variant"), "severity": item.get("severity")}
            for item in variants if item.get("id")]


def _swap_variants() -> None:
    # Callbacks run before widget construction, when these keys may be changed.
    a, b = st.session_state["compare_a"], st.session_state["compare_b"]
    st.session_state["compare_a"], st.session_state["compare_b"] = b, a
    st.session_state["compare_b_pref"] = a


def _styled(df: pd.DataFrame):
    if df.empty or "status" not in df:
        return df
    return df.style.apply(lambda row: [STATUS_STYLE.get(row["status"], "")] * len(row), axis=1)


def _default_evidence(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = sorted(items, key=lambda e: {"measured": 0, "calculated": 1, "synthetic": 2}.get(evidence_kind_label(e), 3))
    return ranked[0] if ranked else None


def render_multi_compare(api_base: str, scenario_id: str, selected: list[dict[str, Any]]) -> None:
    if len(selected) < 2:
        st.info("사이드바에서 비교할 variant를 2개 이상 선택하세요. 첫 번째 항목이 기준입니다.")
        return
    ids = [item["variant_id"] for item in selected]
    reference = ids[0]
    st.markdown(f"**{len(ids)}개 variant 비교** · 기준 `{reference}`")
    labels = short_labels(ids)
    prefix = common_prefix(ids)
    if prefix:
        st.caption(f"열 이름은 공통 prefix `{prefix}`를 생략했습니다. 첫 열이 기준입니다.")
    tab_cond, tab_struct, tab_kpi = st.tabs(["조건 matrix", "DMA 전송 matrix", "Evidence KPI matrix"])
    variant_columns = {labels[vid]: st.column_config.TextColumn(labels[vid], help=vid) for vid in ids}
    with tab_cond:
        keys, constant = differing_keys(selected)
        rows, highlight = condition_matrix(selected, reference, keys)
        df = pd.DataFrame(rows).set_index("조건")
        header_count = 3

        def _cell_style(frame: pd.DataFrame) -> pd.DataFrame:
            styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
            for row_index, column in highlight:
                styles.iloc[row_index, frame.columns.get_loc(column)] = "background-color:#FEF3C7;color:#78350F;font-weight:700"
            for row_index in range(min(header_count, len(frame))):
                styles.iloc[row_index, :] = styles.iloc[row_index, :].where(styles.iloc[row_index, :] != "", "background-color:#F3F4F6;color:#374151")
            return styles

        st.dataframe(df.style.apply(_cell_style, axis=None), use_container_width=True,
                     height=min(40 + 35 * len(df), 720), column_config=variant_columns)
        if constant:
            with st.expander(f"공통 조건 {len(constant)}개 (모든 variant 동일)"):
                st.markdown(" ".join(f"`{key}={value}`" for key, value in constant.items()))
        st.caption("노란 셀 = 기준(파생 variant는 부모)과 다른 값 · — = 미등록 · 열 머리에 마우스를 올리면 전체 variant id가 보입니다.")
    with tab_struct:
        only_diff = st.toggle("variant 간 다른 전송만", value=True, key="compare_multi_dma_diff")
        try:
            rows_by_variant = {vid: dma_rows(_view(api_base, scenario_id, vid)) for vid in ids}
        except (ViewerApiError, ValueError) as exc:
            st.error(f"L1 view를 불러오지 못했습니다: {exc}")
            rows_by_variant = {}
        matrix = dma_matrix(rows_by_variant, only_different=only_diff) if rows_by_variant else []
        if matrix:
            dma_df = pd.DataFrame(matrix).rename(columns=labels).set_index("transfer")
            st.dataframe(dma_df, use_container_width=True, height=min(40 + 35 * len(dma_df), 640),
                         column_config=variant_columns)
        else:
            st.success("선택한 variant들의 M2M 전송이 동일합니다.")
        st.caption("행 = Producer → Buffer → Consumer, 셀 = size · format · compression, — = 해당 variant에 없는 전송.")
    with tab_kpi:
        chosen: dict[str, dict[str, Any] | None] = {}
        for vid in ids:
            try:
                chosen[vid] = _default_evidence(_evidence(api_base, scenario_id, vid))
            except ViewerApiError:
                chosen[vid] = None
        kpi = kpi_matrix_wide(chosen, reference)
        if len(kpi) > 1:
            st.dataframe(pd.DataFrame(kpi).set_index("KPI"), use_container_width=True, column_config=variant_columns)
        else:
            st.info("비교 가능한 KPI가 있는 evidence가 없습니다.")
        with st.expander("사용한 evidence id (measured → calculated → synthetic 순 자동 선택)"):
            st.dataframe(pd.DataFrame([{"variant": vid, "evidence": str(ev["id"]) if ev else "없음"} for vid, ev in chosen.items()]),
                         hide_index=True, use_container_width=True)
        if len({evidence_kind_label(ev) for ev in chosen.values() if ev}) > 1:
            st.warning("variant마다 evidence 출처가 다릅니다. 차이에 모델 오차가 섞일 수 있습니다.")


# ---------------------------------------------------------------------------
# Sidebar: shared context + A/B selection
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Variant Compare")
    api_base = st.text_input("API Base", value=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
                             key="compare_api_base")
    adopted = adopt_query_context(st.query_params, st.session_state, page="compare",
                                  reset_keys=("compare_soc", "compare_project", "compare_scenario", "compare_a", "compare_b"))
    if adopted and st.query_params.get("variant_b"):
        st.session_state["compare_b_pref"] = str(st.query_params.get("variant_b"))
    if "compare_mode" not in st.session_state or (adopted and st.query_params.get("variants")):
        st.session_state["compare_mode"] = "다중 (N개)" if st.query_params.get("variants") else "A/B"
        st.session_state.pop("compare_multi", None)
    ctx = current_context(st.session_state)
    try:
        socs = _socs(api_base)
        soc_id = _pick("SoC Platform", [str(i["id"]) for i in socs if i.get("id")], ctx["soc_id"], "compare_soc",
                       lambda v: compact_soc_label(next((i for i in socs if i.get("id") == v), {"id": v})))
        projects = _projects(api_base, soc_id)
        project_id = _pick("Project / Board", [str(i["id"]) for i in projects if i.get("id")], ctx["project_id"], "compare_project",
                           lambda v: compact_project_label(next((i for i in projects if i.get("id") == v), {"id": v})))
        scenarios = _scenarios(api_base, project_id)
        scenario_id = _pick("Scenario", [str(i["id"]) for i in scenarios if i.get("id")], ctx["scenario_id"] or "uc-camera-recording",
                            "compare_scenario",
                            lambda v: compact_scenario_label(next((i for i in scenarios if i.get("id") == v), {"id": v})))
        variants = _variants(api_base, scenario_id) if scenario_id else []
    except ViewerApiError as exc:
        st.error(f"API unavailable: {exc}")
        st.stop()
    items = _as_items(variants)
    variant_ids = sorted(item["variant_id"] for item in items)
    st.divider()
    variant_a = _pick("Variant A (기준)", variant_ids, ctx["variant_id"] or medoid_variant_id(items), "compare_a")
    others = [vid for vid in variant_ids if vid != variant_a] or variant_ids
    by_id = {item["variant_id"]: item for item in items}
    default_b = st.session_state.get("compare_b_pref") or (by_id.get(variant_a, {}).get("derived_from_variant") or "")
    if default_b not in others:
        # Nearest neighbour by condition distance keeps the default comparison meaningful.
        from dashboard.components.variant_compare import condition_distance
        default_b = min(others, key=lambda vid: (condition_distance(by_id[vid], by_id.get(variant_a, {})), vid)) if others else ""
    variant_b = _pick("Variant B", others, default_b, "compare_b")
    st.button("A ↔ B 교체", use_container_width=True, disabled=not (variant_a and variant_b), on_click=_swap_variants)
    st.divider()
    mode = st.radio("비교 모드", ["A/B", "다중 (N개)"], key="compare_mode", horizontal=True,
                    help="A/B는 구조·예측/실측까지 상세 비교, 다중은 최대 8개 variant의 조건·DMA·KPI를 한 표로 비교합니다.")
    multi: list[str] = []
    if mode == "다중 (N개)":
        wanted = [vid for vid in str(st.query_params.get("variants") or "").split(",") if vid in variant_ids]
        if "compare_multi" not in st.session_state:
            st.session_state["compare_multi"] = wanted or [vid for vid in (variant_a, variant_b) if vid]
        multi = st.multiselect("비교 variant (첫 항목 = 기준)", variant_ids, key="compare_multi", max_selections=8)
    set_context(st.session_state, soc_id=soc_id, project_id=project_id, scenario_id=scenario_id,
                variant_id=(multi[0] if multi else variant_a))
    publish_query(st.query_params, current_context(st.session_state), page="compare", state=st.session_state)
    if mode == "다중 (N개)":
        st.query_params["variants"] = ",".join(multi)
        st.query_params.pop("variant_b", None)
    else:
        st.query_params.pop("variants", None)
        if variant_b:
            st.query_params["variant_b"] = variant_b

render_page_header("Variant Compare", "두 variant의 조건 · pipeline 구조 · evidence KPI와 예측/실측을 나란히 비교합니다.",
                   chips=("Conditions", "Pipeline structure", "Evidence", "Prediction vs Measurement"))
render_context_bar(st.session_state, active="Compare")

if mode == "다중 (N개)":
    render_multi_compare(api_base, scenario_id, [by_id[vid] for vid in multi])
    st.stop()

if not (variant_a and variant_b):
    st.info("비교할 variant가 2개 이상 필요합니다.")
    st.stop()

item_a, item_b = by_id[variant_a], by_id[variant_b]
conditions = condition_diff(item_a, item_b)
changed_conditions = [row for row in conditions if row["status"] != "same"]

try:
    view_a, view_b = _view(api_base, scenario_id, variant_a), _view(api_base, scenario_id, variant_b)
    structure_error = None
except (ViewerApiError, ValueError) as exc:
    view_a = view_b = {"nodes": [], "edges": []}
    structure_error = str(exc)
units = unit_diff(view_a, view_b)
dma = dma_diff(dma_rows(view_a), dma_rows(view_b))
dma_changed = [row for row in dma if row["status"] != "same"]

ctx_now = current_context(st.session_state)
link_a = page_url("/Pipeline_Viewer", {**ctx_now, "variant_id": variant_a})
link_b = page_url("/Pipeline_Viewer", {**ctx_now, "variant_id": variant_b})
m1, m2, m3, m4 = st.columns(4)
m1.metric("A", variant_a)
m2.metric("B", variant_b)
m3.metric("조건 차이", len(changed_conditions))
m4.metric("IP 차이 / DMA 차이", f"{len(units['a_only']) + len(units['b_only'])} / {len(dma_changed)}")
st.markdown(f'<a href="{link_a}" target="_self">A를 Pipeline에서 열기</a> · <a href="{link_b}" target="_self">B를 Pipeline에서 열기</a>',
            unsafe_allow_html=True)

tab_cond, tab_struct, tab_kpi, tab_pm = st.tabs(["조건", "Pipeline 구조", "Evidence KPI (A vs B)", "예측 vs 실측"])

with tab_cond:
    show_same = st.toggle("동일한 조건도 표시", value=False, key="compare_show_same")
    rows = conditions if show_same else changed_conditions
    if rows:
        st.dataframe(_styled(pd.DataFrame(rows)), hide_index=True, use_container_width=True,
                     height=min(40 + 35 * len(rows), 600))
    else:
        st.success("두 variant의 design condition이 동일합니다.")
    parent_a, parent_b = item_a.get("derived_from_variant"), item_b.get("derived_from_variant")
    if parent_a or parent_b:
        st.caption(f"파생 관계: A ← {parent_a or '-'} · B ← {parent_b or '-'} (조건은 부모와 병합된 유효값)")

with tab_struct:
    if structure_error:
        st.error(f"L1 view를 불러오지 못했습니다: {structure_error}")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**A에만 있는 IP/SW**<br>" + (", ".join(f"`{u}`" for u in units["a_only"]) or "없음"), unsafe_allow_html=True)
    c2.markdown("**B에만 있는 IP/SW**<br>" + (", ".join(f"`{u}`" for u in units["b_only"]) or "없음"), unsafe_allow_html=True)
    c3.markdown(f"**공통** {len(units['common'])}개")
    st.markdown("**DMA / Buffer 전송 차이** (Producer → Buffer → Consumer)")
    show_same_dma = st.toggle("동일한 전송도 표시", value=False, key="compare_show_same_dma")
    dma_shown = dma if show_same_dma else dma_changed
    if dma_shown:
        st.dataframe(_styled(pd.DataFrame(dma_shown)), hide_index=True, use_container_width=True,
                     height=min(40 + 35 * len(dma_shown), 560))
    else:
        st.success("M2M 전송(포트·크기·포맷·압축)이 동일합니다.")
    st.caption("빨강 = A에만 있음, 파랑 = B에만 있음, 노랑 = 크기/포맷/bit/압축/포트 변경. L1 view projection 기준입니다.")

with tab_kpi:
    try:
        evidence_a, evidence_b = _evidence(api_base, scenario_id, variant_a), _evidence(api_base, scenario_id, variant_b)
    except ViewerApiError as exc:
        st.error(f"Evidence 목록을 불러오지 못했습니다: {exc}")
        evidence_a = evidence_b = []

    ka, kb = st.columns(2)
    with ka:
        ids_a = [str(e["id"]) for e in evidence_a]
        chosen_a = _pick("A evidence", ids_a, str((_default_evidence(evidence_a) or {}).get("id") or ""), f"compare_ev_a::{variant_a}",
                         lambda v: evidence_option_label(next(e for e in evidence_a if str(e["id"]) == v)))
    with kb:
        ids_b = [str(e["id"]) for e in evidence_b]
        chosen_b = _pick("B evidence", ids_b, str((_default_evidence(evidence_b) or {}).get("id") or ""), f"compare_ev_b::{variant_b}",
                         lambda v: evidence_option_label(next(e for e in evidence_b if str(e["id"]) == v)))
    ev_a = next((e for e in evidence_a if str(e["id"]) == chosen_a), None)
    ev_b = next((e for e in evidence_b if str(e["id"]) == chosen_b), None)
    if ev_a and ev_b and evidence_kind_label(ev_a) != evidence_kind_label(ev_b):
        st.warning(f"출처가 다릅니다: A={evidence_kind_label(ev_a)}, B={evidence_kind_label(ev_b)}. 차이에 모델 오차가 섞입니다.")
    kpi_rows = kpi_side_by_side(ev_a, ev_b)
    if kpi_rows:
        st.dataframe(pd.DataFrame(kpi_rows), hide_index=True, use_container_width=True)
    else:
        st.info("비교 가능한 KPI가 있는 evidence가 없습니다.")

with tab_pm:
    target = st.radio("대상 variant", [variant_a, variant_b], horizontal=True, key="compare_pm_target")
    try:
        target_evidence = _evidence(api_base, scenario_id, target)
    except ViewerApiError as exc:
        st.error(str(exc))
        target_evidence = []
    sims = [e for e in target_evidence if e.get("kind") == "evidence.simulation"]
    meas = [e for e in target_evidence if e.get("kind") == "evidence.measurement"]
    p1, p2 = st.columns(2)
    with p1:
        prediction_id = _pick("예측 (simulation)", [str(e["id"]) for e in sims], "", f"compare_pm_pred::{target}")
    with p2:
        measurement_id = _pick("실측 (measurement)", [str(e["id"]) for e in meas], "", f"compare_pm_meas::{target}",
                               lambda v: evidence_option_label(next(e for e in meas if str(e["id"]) == v)))
    if not (prediction_id and measurement_id):
        st.info("이 variant에는 예측과 실측 evidence가 모두 있어야 비교할 수 있습니다.")
    else:
        try:
            result = _pm_compare(api_base, prediction_id, measurement_id)
        except ViewerApiError as exc:
            st.error(f"비교 API 실패: {exc}")
            result = {}
        if result:
            context = result.get("context") or {}
            if not context.get("compatible", True):
                st.error("실행 조건 불일치(blocking): " + ", ".join(context.get("blocking_mismatches") or []))
            summary = result.get("summary") or {}
            s1, s2, s3 = st.columns(3)
            s1.metric("Matched metrics", summary.get("matched", 0))
            s2.metric("예측만", summary.get("prediction_only", 0))
            s3.metric("실측만", summary.get("measurement_only", 0))
            chart_rows = domain_chart_rows(result)
            if chart_rows and not any(row["side"] == "예측" for row in chart_rows):
                st.warning("예측 evidence에 power domain 분해가 없어 실측만 표시됩니다. 예측 total과의 비교는 아래 표의 power.total 행을 보세요.")
            unmapped = rails_without_domain(next((e for e in meas if str(e["id"]) == measurement_id), None))
            if unmapped:
                total = sum(power for _, power in unmapped)
                st.caption(f"domain 미지정 rail {len(unmapped)}개({total:.1f} mW)는 domain 차트에서 빠집니다: "
                           + ", ".join(f"{rail} {power:.1f}" for rail, power in unmapped[:6]))
            if chart_rows:
                import plotly.express as px

                fig = px.bar(pd.DataFrame(chart_rows), x="domain", y="mW", color="side", barmode="group",
                             color_discrete_map={"예측": "#2563EB", "실측": "#D97706"}, height=340)
                fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), legend_title_text="",
                                  title="Power domain (mW)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("power.domain으로 join되는 항목이 없습니다. 실측 rail에 domain을 지정하고, 예측 쪽 domain 분해가 필요합니다.")
            category = st.selectbox("Metric 범위", ["전체", "power.", "latency", "bw", "fps"], key="compare_pm_filter")
            rows = pm_rows(result, metric_filter=None if category == "전체" else category)
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                             height=min(40 + 35 * len(rows), 560))
            with st.expander("실행 context 비교"):
                st.dataframe(pd.DataFrame(context.get("rows") or []), hide_index=True, use_container_width=True)
            st.caption("PREDICTION_ONLY / MEASUREMENT_ONLY는 반대편에 같은 metric·scope가 없다는 뜻입니다. Simulation 로직/값은 별도 보정 예정이며 이 화면은 비교 구조를 보여줍니다.")
