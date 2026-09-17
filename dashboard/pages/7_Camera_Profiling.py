"""Curated camera import and SW timing exploration."""

import os
import sys
from pathlib import Path
import streamlit as st

root = Path(__file__).resolve().parents[2]
for path in (root, root / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from dashboard.components.camera_profiling import render_camera_import, render_projection

st.set_page_config(page_title="Camera Profiling", layout="wide")
st.title("Camera Profiling")
api_base = st.sidebar.text_input(
    "API Base", os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1")
)
import_tab, projection_tab = st.tabs(["Import / Review", "SW Projection"])
with import_tab:
    render_camera_import(api_base)
with projection_tab:
    render_projection(api_base)

with st.expander("RT/NRT model comparison"):
    from dashboard.components.simulation_api_client import _request_json
    from dashboard.components.viewer_api_client import ViewerApiError

    measurement = st.text_input("Measurement evidence ID")
    prediction = st.text_input("Prediction evidence ID")
    if st.button("Compare stage boundaries"):
        try:
            result = _request_json(
                "GET",
                api_base,
                "/profiling/stage-comparison",
                params={"measurement_id": measurement, "prediction_id": prediction},
            )
            st.dataframe(result["rows"], hide_index=True)
            for note in result["notes"]:
                st.caption(note)
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)
