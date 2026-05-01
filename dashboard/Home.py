"""ScenarioDB dashboard home page.

Run:
    uv run --group dashboard streamlit run dashboard/Home.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


st.set_page_config(
    page_title="ScenarioDB Dashboard",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  footer, #MainMenu { display: none !important; }
  .block-container { padding-top: 1.0rem !important; }
  .home-card {
    border: 1px solid #E8E4DF;
    border-radius: 12px;
    padding: 14px 16px;
    background: #FFFFFF;
    min-height: 178px;
  }
  .home-card h3 {
    margin: 0 0 8px 0;
    color: #111827;
    font-size: 17px;
  }
  .home-card p {
    color: #4B5563;
    font-size: 13px;
    line-height: 1.45;
  }
  .status-ready {
    color: #065F46;
    background: #ECFDF5;
    border: 1px solid #A7F3D0;
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
  }
  .status-later {
    color: #6B7280;
    background: #F3F4F6;
    border: 1px solid #E5E7EB;
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
  }
</style>
""",
    unsafe_allow_html=True,
)

st.title("ScenarioDB Dashboard")
st.markdown("Mobile SoC multimedia scenario database: import, review, and architecture viewer.")
st.divider()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        """
<div class="home-card">
  <h3>DB Explorer</h3>
  <p>Database-level overview, scenario catalog, variant matrix, and import health checks.</p>
  <span class="status-ready">Available</span>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("Open DB Explorer", type="primary", use_container_width=True):
        st.switch_page("pages/1_DB_Explorer.py")

with col2:
    st.markdown(
        """
<div class="home-card">
  <h3>Pipeline Viewer</h3>
  <p>Level 0 architecture, task topology, Level 1 IP detail, and Level 2 drill-down views.</p>
  <span class="status-ready">Available</span>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("Open Pipeline Viewer", use_container_width=True):
        st.switch_page("pages/2_Pipeline_Viewer.py")

with col3:
    st.markdown(
        """
<div class="home-card">
  <h3>Import Workbench</h3>
  <p>Review generated canonical YAML, stage import bundles, validate, diff, and apply through Write API.</p>
  <span class="status-ready">Available</span>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("Open Import Workbench", use_container_width=True):
        st.switch_page("pages/3_Import_Workbench.py")

with col4:
    st.markdown(
        """
<div class="home-card">
  <h3>Evidence Dashboard</h3>
  <p>KPI comparison, feasibility charts, and SW regression analysis across variants.</p>
  <span class="status-later">Deferred</span>
</div>
""",
        unsafe_allow_html=True,
    )
    st.button("Evidence Dashboard", disabled=True, use_container_width=True)

st.divider()
st.caption("ScenarioDB v0.1.0 | Read API, Write API staging, import bundle, and viewer MVP")
