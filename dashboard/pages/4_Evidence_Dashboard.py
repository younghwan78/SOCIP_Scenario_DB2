r"""Simulation evidence dashboard for ScenarioDB.

Run from the project virtual environment:
  .\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.evidence_context import default_silicon_rev, render_evidence_context_sidebar
from dashboard.components.evidence_results_panel import clear_evidence_results_cache, render_evidence_results_panel
from dashboard.components.evidence_run_panel import clear_evidence_run_caches, render_evidence_run_panel
from dashboard.components.ui_theme import apply_app_theme, render_page_header


st.set_page_config(
    page_title="Evidence Dashboard - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  .block-container { padding-top: 0.6rem !important; max-width: none !important; }
  footer, #MainMenu { display: none !important; }
  .metric-row {
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 10px 12px;
    background: #FFFFFF;
  }
  .metric-row b { font-size: 13px; color: #111827; }
  .metric-row span { font-size: 12px; color: #64748B; }
  .viewer-tab-link {
    display: block;
    width: 100%;
    box-sizing: border-box;
    border: 1px solid #D1D5DB;
    border-radius: 7px;
    background: #FFFFFF;
    color: #374151 !important;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.4;
    padding: 9px 12px;
    text-align: center;
    text-decoration: none !important;
  }
  .viewer-tab-link:hover {
    border-color: #9CA3AF;
    background: #F9FAFB;
    color: #111827 !important;
  }
</style>
""",
    unsafe_allow_html=True,
)
apply_app_theme(sidebar_width=288)


def _clear_dashboard_caches() -> None:
    clear_evidence_run_caches()
    clear_evidence_results_cache()


render_page_header(
    "Evidence Dashboard",
    "Run scenario/variant simulation as a preview, save only confirmed evidence, and inspect KPI breakdowns.",
    chips=("Preview first", "Confirm to save", "Power/BW/Timing"),
)

with st.sidebar:
    context = render_evidence_context_sidebar(
        default_api_base=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
        on_refresh=_clear_dashboard_caches,
    )

run_col, result_col = st.columns([0.9, 1.6], gap="large")

with run_col:
    render_evidence_run_panel(
        api_base=context.api_base,
        scenario_id=context.scenario_id,
        variant_id=context.variant_id,
        default_silicon_rev=default_silicon_rev(context.soc_id),
        on_persisted=lambda _evidence_id: clear_evidence_results_cache(),
    )

with result_col:
    render_evidence_results_panel(
        api_base=context.api_base,
        scenario_id=context.scenario_id,
        variant_id=context.variant_id,
        soc_id=context.soc_id,
        project_id=context.project_id,
    )
