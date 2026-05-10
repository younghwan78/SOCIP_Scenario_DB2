"""Simulation run form widgets and payload assembly for the Evidence Dashboard."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from dashboard.components.viewer_api_client import sw_profile_label


THERMAL_PRESETS = {
    "normal": {"label": "normal (~25C ambient)", "ambient_temp_c": 25.0, "note": "Room-temperature baseline."},
    "hot": {"label": "hot (~85C chamber)", "ambient_temp_c": 85.0, "note": "Thermal stress / throttling-risk condition."},
    "cold": {"label": "cold (~-20C chamber)", "ambient_temp_c": -20.0, "note": "Cold-start validation condition."},
}

SILICON_REVS = ["EVT0", "EVT1", "EVT1.3", "Custom"]

DEFAULT_DVFS_TABLES = {
    "CSIS": {
        "domain": "CSIS",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
    "CAM": {
        "domain": "CAM",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
    "INTCAM": {
        "domain": "INTCAM",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
    "INT": {
        "domain": "INT",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
}


def render_simulation_run_form(
    *,
    scenario_id: str,
    variant_id: str,
    default_silicon_rev: str,
    sw_profiles: list[dict[str, Any]],
    sw_error: str | None,
) -> dict[str, Any] | None:
    """Render the run form and return a simulation payload after submission."""

    st.subheader("Run Simulation")
    with st.form("run-simulation"):
        _ensure_choice("evidence_silicon_rev", SILICON_REVS, preferred=default_silicon_rev)
        silicon_rev_choice = st.selectbox(
            "Silicon Rev",
            SILICON_REVS,
            key="evidence_silicon_rev",
            help="Typical bring-up revisions are EVT0 and EVT1. Exynos2600 final is EVT1.3. Use Custom for other minor revisions.",
        )
        if silicon_rev_choice == "Custom":
            silicon_rev = st.text_input(
                "Custom Silicon Rev",
                value=st.session_state.get("evidence_custom_silicon_rev", "EVT1.3"),
                key="evidence_custom_silicon_rev",
            )
        else:
            silicon_rev = silicon_rev_choice

        if sw_profiles:
            sw_ids = [str(item.get("id")) for item in sw_profiles if item.get("id")]
            _ensure_choice("evidence_sw_baseline_ref", sw_ids, preferred="sw-vendor-v1.2.3")
            sw_baseline_ref = st.selectbox(
                "SW Baseline",
                sw_ids,
                key="evidence_sw_baseline_ref",
                format_func=lambda value: sw_profile_label(
                    next((item for item in sw_profiles if item.get("id") == value), {"id": value})
                ),
            )
        else:
            if sw_error:
                st.caption(f"SW profile list unavailable: {sw_error}")
            sw_baseline_ref = st.text_input("SW Baseline", key="evidence_sw_baseline_ref_text", value="sw-vendor-v1.2.3")

        _ensure_choice("evidence_thermal", list(THERMAL_PRESETS), preferred="normal")
        thermal = st.selectbox(
            "Thermal",
            list(THERMAL_PRESETS),
            key="evidence_thermal",
            format_func=lambda value: THERMAL_PRESETS[value]["label"],
            help="normal/hot/cold are execution-context buckets. The ambient temperature value is also sent in execution_context.",
        )
        st.caption(THERMAL_PRESETS[thermal]["note"])
        asv_group = st.number_input("ASV Group", min_value=0, max_value=8, value=4, step=1, key="evidence_asv_group")
        fps_value = st.text_input("FPS Override", value="", key="evidence_fps_override")
        include_timeline = st.checkbox("Include timing timeline", value=True, key="evidence_include_timeline")
        timeline_frame_count = st.number_input(
            "Timeline Frames",
            min_value=1,
            max_value=16,
            value=4,
            step=1,
            key="evidence_timeline_frame_count",
            help="Use multiple frames for buffered M2M/display cadence analysis. Single-frame latency can exceed one frame period and still meet steady-state cadence.",
            disabled=not include_timeline,
        )
        force = st.checkbox("Force recompute", value=False, key="evidence_force_recompute")
        debug_trace = st.checkbox(
            "Debug calculation trace",
            value=False,
            key="evidence_debug_trace",
            help="Attach formula-level calculation details to the preview. It is saved to DB only when you confirm the result.",
        )
        debug_trace_level = st.selectbox(
            "Debug detail",
            ["formula", "summary", "full"],
            key="evidence_debug_trace_level",
            help="formula is the normal debug mode. summary is compact; full is reserved for deeper timing details.",
            disabled=not debug_trace,
        )
        default_dvfs_json = json.dumps(DEFAULT_DVFS_TABLES, indent=2)
        if "evidence_dvfs_json" not in st.session_state:
            st.session_state["evidence_dvfs_json"] = default_dvfs_json
        dvfs_json = st.text_area(
            "DVFS Tables JSON",
            key="evidence_dvfs_json",
            height=220,
            help="Schema: domain -> {domain, levels:[{level, speed_mhz, voltages:{asv_group: millivolts}}]}. Keys must match IP dvfs_group values such as CAM, CSIS, INTCAM, INT.",
        )
        with st.expander("DVFS JSON help", expanded=False):
            st.markdown(
                "`speed_mhz` is the available DVFS clock. `voltages` maps ASV group to mV. "
                "If a domain is omitted, simulation falls back to the reference voltage for power calculation."
            )
        st.caption("Simulation runs are preview-only by default. Use Confirm & Save Evidence after reviewing the result.")
        submitted = st.form_submit_button("Run Preview", type="primary", use_container_width=True)

    if not submitted:
        return None

    try:
        dvfs_tables = json.loads(dvfs_json or "{}")
        fps = float(fps_value) if fps_value.strip() else None
    except json.JSONDecodeError as exc:
        st.error(f"DVFS JSON is invalid: {exc}")
        return None
    except ValueError as exc:
        st.error(str(exc))
        return None

    return {
        "scenario_id": scenario_id,
        "variant_id": variant_id,
        "execution_context": {
            "silicon_rev": silicon_rev,
            "sw_baseline_ref": sw_baseline_ref,
            "thermal": thermal,
            "ambient_temp_c": THERMAL_PRESETS[thermal]["ambient_temp_c"],
        },
        "config": {
            "asv_group": asv_group,
            "fps": fps,
            "include_timeline": include_timeline,
            "timeline_frame_count": int(timeline_frame_count),
            "debug_trace": debug_trace,
            "debug_trace_level": debug_trace_level,
        },
        "dvfs_tables": dvfs_tables,
        "persist": False,
        "force": force,
    }


def _ensure_choice(key: str, options: list[str], preferred: str | None = None) -> None:
    if not options:
        return
    current = st.session_state.get(key)
    if current in options:
        return
    st.session_state[key] = preferred if preferred in options else options[0]
