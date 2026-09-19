"""Board catalogs and reusable sensor readout timing."""
import json
import os
import sys
from pathlib import Path
import streamlit as st
root = Path(__file__).resolve().parents[2]
for path in (root, root / "src"):
    if str(path) not in sys.path: sys.path.insert(0, str(path))
from dashboard.components.simulation_api_client import _request_json
from dashboard.components.viewer_api_client import ViewerApiError

st.set_page_config(page_title="Sensor Catalog", layout="wide")
st.title("Sensor Catalog / Valid Time")
base = st.sidebar.text_input("API Base", os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"))
try:
    items = _request_json("GET", base, "/sensors/catalogs")["items"]
    boards = sorted({x["board"] for x in items})
    if not boards:
        st.info("Import sensor catalogs using the strict ETL CLI first."); st.stop()
    board = st.selectbox("Source board", boards)
    ids = [x["id"] for x in items if x["board"] == board]
    selected = st.selectbox("Sensor catalog", ids)
    doc = _request_json("GET", base, f"/sensors/catalogs/{selected}")["document"]
    label = st.selectbox("Full DT mode", list(doc["modes"]))
    result = _request_json("GET", base, f"/sensors/catalogs/{selected}/modes/{label}/timing")
    st.json(result)
    with st.expander("DT mode / VC / wiring"):
        st.json({"mode": doc["modes"][label], "wiring": doc["csis_wiring"]})
    st.subheader("Reusable CIS timing")
    st.caption("CIS modes are separate from DT modes. A matching size/FPS does not establish equivalence. Readout predicts the CSIS frame window; it is not an observed FS/FE measurement.")
    profiles = _request_json("GET", base, "/sensors/timing-profiles", params={"sensor_name": doc["sensor_name"]})["items"]
    if profiles:
        profile_id = st.selectbox("Timing profile", [x["id"] for x in profiles])
        profile = next(x for x in profiles if x["id"] == profile_id)
        mode = st.selectbox("CIS mode", profile["modes"])
        timing = _request_json("GET", base, f"/sensors/timing-profiles/{profile_id}/modes/{mode}")
        a,b,c = st.columns(3)
        a.metric("VVALID / CSIS window (ms)", f"{timing['valid_time_ms']:.6f}")
        b.metric("Frame period (ms)", f"{timing['frame_period_ms']:.6f}")
        c.metric("Vertical blank (ms)", f"{timing['vertical_blank_ms']:.6f}")
        st.json(timing)
        node_id = st.text_input("Target simulation sensor node ID", "sensor_rear")
        st.download_button("Download readout exploration config", json.dumps({"sensor_readout": {node_id: timing["inputs"]}}, indent=2), file_name="sensor-readout-config.json", mime="application/json")
    else:
        st.info("No verified CIS timing profile is imported for this sensor.")
except ViewerApiError as exc:
    st.error(str(exc))
