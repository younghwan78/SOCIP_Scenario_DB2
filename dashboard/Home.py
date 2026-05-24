"""ScenarioDB dashboard home page.

Run:
    uv run --group dashboard streamlit run dashboard/Home.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.ui_theme import apply_app_theme, render_page_header


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
  .home-tile {
    width: 100%;
    display: flex;
    flex-direction: column;
  }
  .home-logo-panel {
    width: 100%;
    aspect-ratio: 1 / 1;
    border: 1px solid #E8E4DF;
    border-bottom: 0;
    border-radius: 12px 12px 0 0;
    background: #FFFFFF;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  }
  .home-tile-logo {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
    transform: scale(1.018);
  }
  .home-card {
    border: 1px solid #E8E4DF;
    border-radius: 0 0 12px 12px;
    padding: 16px 16px 14px 16px;
    background: #FFFFFF;
    min-height: 178px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
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
apply_app_theme(sidebar_width=288)

ASSET_DIR = _root / "dashboard" / "assets"
HOME_TILE_LOGOS = {
    "DB Explorer": "ScenarioDB_DBexplorer.png",
    "Pipeline Viewer": "ScenarioDB_PipelineViewer.png",
    "Architecture Query": "ScenarioDB_ArchitectureQuery.png",
    "Evidence Dashboard": "ScenarioDB_EvidenceDashboard.png",
    "Exploration Workbench": "ScenarioDB_ExplorationWorkbench.png",
    "Import Workbench": "ScenarioDB_ImportWorkbench.png",
}


@st.cache_data(show_spinner=False)
def _asset_data_uri(asset_name: str) -> str:
    data = (ASSET_DIR / asset_name).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _home_card(title: str, description: str) -> str:
    logo = _asset_data_uri(HOME_TILE_LOGOS[title])
    return f"""
<div class="home-tile">
  <div class="home-logo-panel">
    <img class="home-tile-logo" src="{logo}" alt="{title} logo">
  </div>
  <div class="home-card">
    <h3>{title}</h3>
    <p>{description}</p>
    <span class="status-ready">Available</span>
  </div>
</div>
"""

render_page_header(
    "ScenarioDB Dashboard",
    "Mobile SoC multimedia scenario database: import, review, simulation, exploration, and architecture viewer.",
    chips=("Read API", "Write staging", "Simulation", "Exploration", "Viewer"),
)

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.markdown(
        _home_card(
            "DB Explorer",
            "Database-level overview, scenario catalog, variant matrix, and import health checks.",
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open DB Explorer", use_container_width=True):
        st.switch_page("pages/1_DB_Explorer.py")

with col2:
    st.markdown(
        _home_card(
            "Pipeline Viewer",
            "Level 0 architecture, task topology, Level 1 IP detail, and Level 2 drill-down views.",
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open Pipeline Viewer", use_container_width=True):
        st.switch_page("pages/2_Pipeline_Viewer.py")

with col3:
    st.markdown(
        _home_card(
            "Architecture Query",
            "Filter variants by design axis, effective topology, buffer usage, and latest evidence KPI conditions.",
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open Architecture Query", use_container_width=True):
        st.switch_page("pages/3_Architecture_Query.py")

with col4:
    st.markdown(
        _home_card(
            "Evidence Dashboard",
            "Run BW, power, and timing simulation, persist evidence, and inspect per-IP breakdowns.",
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open Evidence Dashboard", use_container_width=True):
        st.switch_page("pages/4_Evidence_Dashboard.py")

with col5:
    st.markdown(
        _home_card(
            "Exploration Workbench",
            "Load exploration recipes or sweeps, compile candidates, run preview simulations, and compare KPI deltas.",
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open Exploration Workbench", use_container_width=True):
        st.switch_page("pages/5_Exploration_Workbench.py")

with col6:
    st.markdown(
        _home_card(
            "Import Workbench",
            "Review generated canonical YAML, stage import bundles, validate, diff, and apply through Write API.",
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open Import Workbench", use_container_width=True):
        st.switch_page("pages/6_Import_Workbench.py")

st.divider()
st.caption("ScenarioDB v0.1.0 | Read API, Write API staging, import bundle, simulation, exploration, query, and viewer MVP")
