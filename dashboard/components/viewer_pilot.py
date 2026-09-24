"""L0 pilot: scoped evidence and a single shared timeline/topology component."""
from __future__ import annotations

from urllib.parse import quote
import streamlit as st

from dashboard.components.viewer_api_client import ViewerApiError, _request_json
from dashboard.components.viewer_timing_panel import _load_simulation_result
from dashboard.components.workbench import _get_component
from dashboard.components.workbench_data import build_component_args, build_graph_payload

PILOT_VARIANT = "cam-rec-r1-uhd30-vdis"


def pilot_payload(result, view):
    if (result.get("scenario_ref"), result.get("variant_ref"), result.get("project_ref")) != (
        view.scenario_id, view.variant_id, "proj-sm-s947b"
    ):
        raise ValueError("Timing evidence does not belong to this pilot view")
    events = [dict(e) for e in result.get("timeline_events") or []]
    by_id = {e["task_id"]: e for e in events}
    anchors = {(e["source_task_id"], e["target_task_id"]): e.get("source_anchor", "end")
               for e in (result.get("pipeline_model") or {}).get("edges", [])}
    for event in events:
        event["display_name"] = event.get("source_slice_name") or event.get("logical_task_id") or event.get("node_id") or event["task_id"]
        event["track_name"] = event.get("resource_name") or event.get("node_id") or event.get("resource_id") or "Other"
        event["predecessor_anchors"] = {p: anchors.get((by_id[p].get("logical_task_id"), event.get("logical_task_id")), "end")
                                        for p in event.get("predecessors", []) if p in by_id}
    args = build_component_args(events, show_deadlines=False, show_waits=False,
                                frame_interval_ms=1000 / 30, export_name=str(result["id"]))
    view_data = view.model_dump(mode="json")
    graph = build_graph_payload(view_data) or {"nodes": [], "edges": []}
    details = {n["data"]["id"]: n["data"] for n in view_data.get("nodes", [])}
    for node in graph["nodes"]:
        node["properties"] = details.get(node["id"], {})
    graph["pilotLayout"] = True
    args.update(graph=graph, pilot=True,
                stateKey=f"pilot:{view.scenario_id}:{view.variant_id}:{result['id']}")
    return args


def render_pilot(*, api_base, view, simulation_id):
    st.markdown("#### Pipeline · Timing")
    source_key = f"pilot_source_{view.scenario_id}_{view.variant_id}"
    try:
        response = _request_json("GET", api_base, "/evidence", params={
            "scenario_ref": view.scenario_id, "variant_ref": view.variant_id,
            "project_ref": "proj-sm-s947b", "kind": "evidence.measurement", "limit": 100})
        traces = [item for item in response.get("items", []) if item.get("pipeline_model") and item.get("timeline_events")]
        choices = {str(item["id"]): "Trace · " + str(item["id"]) for item in traces}
        if simulation_id:
            choices[simulation_id] = "모델 계산 · " + simulation_id
        if not choices:
            st.info("Timing 이벤트가 있는 evidence가 없습니다. Camera Profiling에서 trace를 import하거나 simulation을 저장하세요.")
            return False
        chosen = st.selectbox("Timing 데이터", list(choices), format_func=choices.get, key=source_key)
        if chosen == simulation_id:
            result = _load_simulation_result(api_base, chosen, view.scenario_id, view.variant_id)
        else:
            result = _request_json("GET", api_base, "/evidence/" + quote(chosen, safe=""))
        scope = (result.get("profiling_metadata") or {}).get("measurement_scope")

        events = result.get("timeline_events") or []
        frames = {e.get("frame_index") for e in events if e.get("frame_index") is not None}
        source_label = "모델 계산" if chosen == simulation_id else "Trace"
        if scope and "synthetic" in scope.lower():
            source_label = "Synthetic fixture"
        st.caption(f"{source_label} · Preview {len(events)} events / {len(frames)} frames · 33.33ms는 출력 주기 기준")
        with st.expander("데이터 출처 / 지표 해석", expanded=False):
            st.caption(scope or "모델 계산 결과 · Trace 관측값과 구분해서 해석하세요.")
            st.caption("출력 주기와 frame latency는 별도 지표입니다. 33.33ms 선은 frame 주기이며 완료 deadline이 아닙니다.")
        _get_component()(key=f"pilot_l0_{view.scenario_id}_{view.variant_id}", default=None,
                         **pilot_payload(result, view))
        return True
    except (ViewerApiError, ValueError) as exc:
        st.error(f"Timing 데이터를 열지 못했습니다: {exc}")
        return False
