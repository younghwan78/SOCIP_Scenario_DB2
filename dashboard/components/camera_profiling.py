"""Small camera review and import controls."""

from __future__ import annotations
import json
import streamlit as st
from dashboard.components.simulation_api_client import _request_json
from dashboard.components.viewer_api_client import ViewerApiError


def camera_rows(evidence):
    model = evidence.get("pipeline_model") or {}
    active = set((model.get("execution_path") or {}).get("enabled_task_ids") or [])
    stats = {s["task"]: s for s in evidence.get("sw_task_timing") or []}
    return [
        dict(
            task=t["task_id"],
            stage=t["stage"],
            kind=t["kind"],
            enabled=t["task_id"] in active,
            scope=t.get("timing_scope"),
            mean_ms=stats.get(t["task_id"], {}).get("mean_ms"),
            min_ms=stats.get(t["task_id"], {}).get("min_ms"),
            max_ms=stats.get(t["task_id"], {}).get("max_ms"),
        )
        for t in model.get("tasks") or []
    ]


def sequence_dot(model):
    active = set(model["execution_path"]["enabled_task_ids"])
    lines = ["digraph pipeline { rankdir=LR; node [shape=box];"]
    for task in model["tasks"]:
        color = "#D8ECFF" if task["kind"] == "sw" else "#E8E8E8"
        if task["task_id"] not in active:
            color = "#F7F7F7"
        label = task["label"] + (" (bypass)" if task["task_id"] not in active else "")
        lines.append(
            f'{json.dumps(task["task_id"])} [label={json.dumps(label)}, style=filled, fillcolor="{color}"];'
        )
    for edge in model["edges"]:
        lines.append(
            f"{json.dumps(edge['source_task_id'])} -> {json.dumps(edge['target_task_id'])};"
        )
    return "\n".join([*lines, "}"])


def render_camera(evidence):
    if not evidence.get("pipeline_model"):
        return
    model = evidence["pipeline_model"]
    st.markdown("### Camera pipeline")
    st.caption(
        f"Path: {evidence.get('execution_path_id')} · SW: {(evidence.get('execution_context') or {}).get('sw_baseline_ref')}"
    )
    st.write(model["execution_path"]["description"])
    st.graphviz_chart(sequence_dot(model), use_container_width=True)
    st.dataframe(camera_rows(evidence), hide_index=True, use_container_width=True)
    if model.get("edges"):
        st.caption("Declared sequence; parallel branches retain their dependencies.")
        st.dataframe(model["edges"], hide_index=True, use_container_width=True)
    disabled = model["execution_path"].get("disabled_tasks")
    if disabled:
        st.dataframe(disabled, hide_index=True, use_container_width=True)
    if evidence.get("stage_timing"):
        st.caption(
            "RT/NRT chain span: current-SoC validation only. Never used as target HW runtime."
        )
        st.dataframe(evidence["stage_timing"], hide_index=True, use_container_width=True)
    if evidence.get("sw_event_latency"):
        st.caption("Measured edge gaps (ms)")
        st.dataframe(evidence["sw_event_latency"], hide_index=True, use_container_width=True)
    if evidence.get("timeline_events"):
        import plotly.graph_objects as go

        events = evidence["timeline_events"]
        fig = go.Figure(
            go.Bar(
                x=[e["duration_ms"] for e in events],
                base=[e["start_ms"] for e in events],
                y=[e.get("logical_task_id", e["task_id"]) for e in events],
                orientation="h",
            )
        )
        fig.update_layout(xaxis_title="Time (ms)", barmode="overlay", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Observed bounded window; not necessarily one complete frame.")


def render_camera_import(api_base):
    st.caption(
        "Upload structured camera Markdown, or canonical YAML from the local semantic trace CLI."
    )
    upload = st.file_uploader(
        "Camera profile", type=["md", "yaml", "yml"], key="camera-profile-upload"
    )
    if upload is None:
        return
    if upload.size > 1_000_000:
        st.error("Profile limit is 1 MB")
        return
    try:
        text = upload.getvalue().decode("utf-8-sig")
        if upload.name.endswith(".md"):
            payload = {"markdown": text}
        else:
            from scenario_db.meas_import.camera import UniqueLoader
            import yaml

            payload = {"evidence": yaml.load(text, Loader=UniqueLoader)}
        signature = json.dumps(payload, sort_keys=True)
        if st.button("Preview camera import"):
            st.session_state.pop("camera-preview", None)
            result = _request_json("POST", api_base, "/profiling/import/preview", json=payload)
            st.session_state["camera-preview"] = (signature, result)
        saved = st.session_state.get("camera-preview")
        if saved and saved[0] == signature:
            result = saved[1]
            render_camera(result["evidence"])
            for warning in result["warnings"]:
                st.warning(warning)
            if result["missing_sw_statistics"]:
                st.warning(f"Missing SW statistics: {result['missing_sw_statistics']}")
            st.code(result["sha256"])
            if st.button("Save reviewed camera evidence", type="primary"):
                response = _request_json(
                    "POST",
                    api_base,
                    "/profiling/import/commit",
                    json={**payload, "expected_hash": result["sha256"]},
                )
                st.success(f"{response['status']}: {response['id']}")
    except (ValueError, ViewerApiError) as exc:
        st.error(str(exc))
        if isinstance(exc, ViewerApiError) and exc.body:
            st.code(exc.body)


def render_projection(api_base):
    st.caption(
        "Target variant must already define the intended active HW path. Clock candidates use the existing bounded exploration engine."
    )
    source = st.text_input("Source camera evidence ID")
    project = st.text_input("Target project ID")
    scenario = st.text_input("Target scenario ID")
    variant = st.text_input("Target variant ID")
    path = st.text_input("Target path label")
    mapping = st.text_area("SW mapping JSON (source task → target SW node)", value="{}")
    edges = st.text_area("Latency mapping JSON (source edge → source/target nodes)", value="{}")
    overrides = st.text_area(
        "Runtime adjustments JSON (source task → scale or delta_ms)", value="{}"
    )
    latency_overrides = st.text_area("Latency adjustments JSON", value="{}")
    statistic = st.selectbox("Timing statistic", ["mean", "min", "max"])
    notes = st.text_input("Projection assumptions")
    selection = dict(
        source_evidence_ref=source,
        target_project_ref=project,
        target_scenario_ref=scenario,
        target_variant_ref=variant,
        target_path_id=path,
        statistic=statistic,
        assumption_notes=notes,
    )
    signature = json.dumps([selection, mapping, edges, overrides, latency_overrides])
    try:
        if st.button("Prepare SW projection"):
            st.session_state.pop("camera-projection", None)
            selection.update(
                task_mapping=json.loads(mapping),
                edge_mapping=json.loads(edges),
                runtime_overrides=json.loads(overrides),
                latency_overrides=json.loads(latency_overrides),
            )
            prepared = _request_json(
                "POST", api_base, "/profiling/sw-projection/prepare", json=selection
            )
            st.session_state["camera-projection"] = (signature, prepared)
        saved = st.session_state.get("camera-projection")
        if saved and saved[0] == signature:
            prepared = saved[1]
            st.json(prepared, expanded=False)
            st.download_button(
                "Download projection",
                json.dumps(prepared, indent=2),
                file_name="sw-projection.json",
            )
            axes = st.text_area(
                "Clock candidate axes JSON",
                value="[]",
                help='Example: [{"target":"node_clock_mhz","node_id":"gdc_m","values":[300,400]}]',
            )
            if st.button("Run projection / clock candidates"):
                result = _request_json(
                    "POST",
                    api_base,
                    "/exploration/scenarios/preview",
                    json=dict(
                        project_ref=project,
                        scenario_id=scenario,
                        variant_id=variant,
                        axes=json.loads(axes),
                        config=dict(
                            sw_timing_projection=prepared,
                            include_timeline=True,
                            timeline_frame_count=4,
                        ),
                    ),
                )
                st.dataframe(
                    [
                        dict(
                            case=c["case_id"],
                            feasible=c["feasible"],
                            set_clocks_mhz=c["set_clocks_mhz"],
                            **c["metrics"],
                        )
                        for c in result["cases"]
                    ],
                    hide_index=True,
                )
                st.json(result, expanded=False)
                st.caption(
                    "No evidence saved. Missing CPU/other power domains remain unknown; candidates are not an automatic global optimum."
                )
    except (ValueError, ViewerApiError) as exc:
        st.error(str(exc))
        if isinstance(exc, ViewerApiError) and exc.body:
            st.code(exc.body)
