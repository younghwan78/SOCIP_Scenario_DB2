"""Unit-explicit driver demand explorer."""

import json
import os
import sys
from pathlib import Path
import streamlit as st

root = Path(__file__).resolve().parents[2]
for p in (root, root / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from dashboard.components.simulation_api_client import _request_json
from dashboard.components.viewer_api_client import ViewerApiError

st.set_page_config(page_title="Driver Models", layout="wide")
st.title("Driver BW / DVFS Models")
st.caption(
    "Endpoint demand estimates. BTS vote and surface traffic are separate; values are not added to legacy DMA/power totals. Core power remains uncalibrated."
)
base = st.sidebar.text_input(
    "API Base", os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1")
)
scenario = st.text_input("Scenario ID", "uc-game-play")
variant = st.text_input("Variant ID", "game-fhd-60fps-m2m-upscale")
try:
    report = _request_json(
        "GET", base, "/driver-models", params={"scenario_id": scenario, "variant_id": variant}
    )
    rows = report["rows"]
    st.dataframe(
        [
            {
                k: r.get(k)
                for k in (
                    "node_id",
                    "model",
                    "status",
                    "read_bytes_s",
                    "write_bytes_s",
                    "required_clock_khz",
                    "selected_disp_clock_khz",
                    "power_mw",
                )
            }
            for r in rows
        ],
        hide_index=True,
    )
    with st.expander("Calculation inputs, operating points and provenance"):
        st.json(report)
    available = [r for r in rows if r.get("inputs")]
    if available:
        node = st.selectbox("Endpoint to explore", [r["node_id"] for r in available])
        chosen = next(r for r in available if r["node_id"] == node)
        text = st.text_area(
            "Inputs (JSON)",
            json.dumps(chosen["inputs"], indent=2),
            height=270,
            key=f"{scenario}/{variant}/{node}",
        )
        if st.button("Calculate modified inputs"):
            try:
                inputs = json.loads(text)
            except json.JSONDecodeError as exc:
                st.error(str(exc))
            else:
                result = _request_json(
                    "POST",
                    base,
                    "/driver-models/explore",
                    json={
                        "scenario_id": scenario,
                        "variant_id": variant,
                        "overrides": {node: inputs},
                    },
                )
                st.json(next(r for r in result["rows"] if r["node_id"] == node))
    else:
        st.info("No supported active driver model inputs in this variant.")
except ViewerApiError as exc:
    st.error(str(exc))
