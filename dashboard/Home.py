"""ScenarioDB Viewer — Home page (Streamlit multi-page entry point).

Run:
    uv run --group dashboard streamlit run dashboard/Home.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_root / "dashboard") not in sys.path:
    sys.path.insert(0, str(_root / "dashboard"))

import streamlit as st

st.set_page_config(
    page_title="ScenarioDB Viewer",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  footer { display: none !important; }
  #MainMenu { display: none !important; }
</style>
""", unsafe_allow_html=True)

st.title("🔬 ScenarioDB Viewer")
st.markdown("Mobile SoC Multimedia IP Scenario Database — Architecture Viewer")
st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 🗺️ Pipeline Viewer")
    st.markdown("""
    Level 0 lane architecture view — 6-lane × 4-stage
    Cytoscape.js diagram with SW stack, HW IPs, and buffers.

    **Status:** ✅ Available
    """)
    if st.button("Open Pipeline Viewer →", type="primary"):
        st.switch_page("pages/1_Pipeline_Viewer.py")

with col2:
    st.markdown("### 📊 Evidence Dashboard")
    st.markdown("""
    KPI comparison, feasibility chart, and SW regression
    analysis across variants.

    **Status:** 🔜 Phase C
    """)
    st.button("Evidence Dashboard →", disabled=True)

with col3:
    st.markdown("### 🎯 Issue Explorer")
    st.markdown("""
    Matched issue browser with gate rule status,
    waiver tracking, and review history.

    **Status:** 🔜 Phase C
    """)
    st.button("Issue Explorer →", disabled=True)

st.divider()
st.caption(
    "ScenarioDB v0.1.0 · Phase B MVP · "
    "[API Reference](../docs/api-reference.md) · "
    "29 GET endpoints"
)
