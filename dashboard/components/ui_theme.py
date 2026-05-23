"""Shared Streamlit UI theme for the ScenarioDB dashboard."""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from typing import Iterable

import streamlit as st
import streamlit.components.v1 as components


SCENARIODB_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
SCENARIODB_SIDEBAR_LOGO = SCENARIODB_ASSET_DIR / "ScenarioDB_sidebar logo.png"


def apply_app_theme(*, sidebar_width: int = 288) -> None:
    """Apply the ScenarioDB balanced engineering console visual theme."""

    sidebar_logo_src = _asset_data_uri(SCENARIODB_SIDEBAR_LOGO) if SCENARIODB_SIDEBAR_LOGO.exists() else ""

    st.markdown(
        f"""
<style>
  :root {{
    --sdb-bg: #F7F4EF;
    --sdb-sidebar: #F1EDE6;
    --sdb-surface: #FFFFFF;
    --sdb-surface-soft: #FBFAF7;
    --sdb-border: #DED8CF;
    --sdb-border-strong: #CFC6BA;
    --sdb-text: #111827;
    --sdb-muted: #667085;
    --sdb-faint: #98A2B3;
    --sdb-primary: #2F6F68;
    --sdb-primary-hover: #255E58;
    --sdb-primary-soft: #E8F1EF;
    --sdb-primary-border: #B9D2CC;
    --sdb-primary-text: #174D47;
    --sdb-teal: #2F6F68;
    --sdb-sage: #6F7F5D;
    --sdb-warm: #A56A2A;
    --sdb-warm-soft: #F5EBDD;
    --sdb-orange: #EA7C00;
    --sdb-danger: #DC2626;
    --sdb-radius: 8px;
    --sdb-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
  }}

  html, body, .stApp, div[data-testid="stAppViewContainer"] {{
    background: var(--sdb-bg) !important;
    color: var(--sdb-text);
  }}

  footer, #MainMenu {{
    display: none !important;
  }}

  header[data-testid="stHeader"] {{
    background: transparent !important;
    box-shadow: none !important;
  }}

  div[data-testid="collapsedControl"] {{
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    z-index: 1000000 !important;
  }}

  div[data-testid="collapsedControl"] button,
  button[title="Show sidebar"],
  button[title="Hide sidebar"],
  button[aria-label="Show sidebar"],
  button[aria-label="Hide sidebar"] {{
    background: var(--sdb-surface) !important;
    border: 1px solid var(--sdb-border-strong) !important;
    border-radius: var(--sdb-radius) !important;
    color: var(--sdb-primary-text) !important;
    box-shadow: var(--sdb-shadow);
    min-width: 30px !important;
    min-height: 30px !important;
    opacity: 1 !important;
  }}

  div[data-testid="collapsedControl"] button:hover,
  button[title="Show sidebar"]:hover,
  button[title="Hide sidebar"]:hover,
  button[aria-label="Show sidebar"]:hover,
  button[aria-label="Hide sidebar"]:hover {{
    background: var(--sdb-primary-soft) !important;
    border-color: var(--sdb-primary-border) !important;
    color: var(--sdb-primary-text) !important;
  }}

  div[data-testid="collapsedControl"] {{
    position: fixed !important;
    top: 14px !important;
    left: 14px !important;
  }}

  .block-container {{
    max-width: none !important;
    padding-top: 0.85rem !important;
    padding-left: 1.35rem !important;
    padding-right: 1.35rem !important;
    padding-bottom: 1.4rem !important;
  }}

  section[data-testid="stSidebar"] {{
    width: {sidebar_width}px !important;
    min-width: {sidebar_width}px !important;
    background: var(--sdb-sidebar) !important;
    border-right: 1px solid var(--sdb-border);
  }}

  section[data-testid="stSidebar"] > div {{
    width: {sidebar_width}px !important;
    background: var(--sdb-sidebar) !important;
    padding-top: 0.9rem;
  }}

  section[data-testid="stSidebar"][aria-expanded="false"] {{
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    border-right: 0 !important;
    background: transparent !important;
    overflow: visible !important;
  }}

  section[data-testid="stSidebar"][aria-expanded="false"] > div {{
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    overflow: visible !important;
    background: transparent !important;
  }}

  section[data-testid="stSidebar"] h1,
  section[data-testid="stSidebar"] h2,
  section[data-testid="stSidebar"] h3 {{
    color: var(--sdb-text);
    font-weight: 800;
    letter-spacing: 0;
  }}

  section[data-testid="stSidebar"] hr {{
    border-color: var(--sdb-border);
  }}

  h1, h2, h3, h4 {{
    color: var(--sdb-text);
    letter-spacing: 0;
  }}

  h1 {{
    font-size: 30px !important;
    line-height: 1.15 !important;
    font-weight: 850 !important;
  }}

  h2 {{
    font-size: 22px !important;
    font-weight: 800 !important;
  }}

  h3 {{
    font-size: 17px !important;
    font-weight: 800 !important;
  }}

  p, label, .stMarkdown, .stCaption, [data-testid="stCaptionContainer"] {{
    color: var(--sdb-muted);
  }}

  div[data-testid="stVerticalBlockBorderWrapper"],
  div[data-testid="stForm"],
  div[data-testid="stExpander"] {{
    border-color: var(--sdb-border) !important;
    border-radius: var(--sdb-radius) !important;
    background: var(--sdb-surface) !important;
    box-shadow: var(--sdb-shadow);
  }}

  div[data-testid="stMetric"] {{
    background: var(--sdb-surface);
    border: 1px solid var(--sdb-border);
    border-radius: var(--sdb-radius);
    padding: 10px 12px;
    box-shadow: var(--sdb-shadow);
  }}

  div[data-testid="stMetric"] label {{
    color: var(--sdb-muted) !important;
    font-size: 12px !important;
    font-weight: 700 !important;
  }}

  div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
    color: var(--sdb-text);
    font-size: 28px;
    font-weight: 800;
  }}

  .stButton > button,
  .stDownloadButton > button,
  div[data-testid="stBaseButton-secondary"] button {{
    border-radius: var(--sdb-radius) !important;
    border: 1px solid var(--sdb-border-strong) !important;
    background: var(--sdb-surface) !important;
    color: #344054 !important;
    font-weight: 700 !important;
    box-shadow: 0 1px 1px rgba(16, 24, 40, 0.04);
  }}

  .stButton > button p,
  .stDownloadButton > button p,
  .stFormSubmitButton > button p {{
    color: inherit !important;
  }}

  .stButton > button:hover,
  .stDownloadButton > button:hover {{
    border-color: var(--sdb-primary) !important;
    color: var(--sdb-primary-text) !important;
    background: var(--sdb-primary-soft) !important;
  }}

  .stButton > button[kind="primary"],
  .stFormSubmitButton > button[kind="primary"],
  button[data-testid="stBaseButton-primary"],
  div[data-testid="stBaseButton-primary"] button,
  div[data-testid="stBaseButton-primary"] > button {{
    background: var(--sdb-primary) !important;
    border-color: var(--sdb-primary) !important;
    color: #FFFFFF !important;
    text-shadow: none !important;
  }}

  .stButton > button[kind="primary"] p,
  .stFormSubmitButton > button[kind="primary"] p,
  button[data-testid="stBaseButton-primary"] p,
  div[data-testid="stBaseButton-primary"] button p,
  div[data-testid="stBaseButton-primary"] > button p {{
    color: #FFFFFF !important;
  }}

  .stButton > button[kind="primary"]:hover,
  .stFormSubmitButton > button[kind="primary"]:hover,
  button[data-testid="stBaseButton-primary"]:hover,
  div[data-testid="stBaseButton-primary"] button:hover,
  div[data-testid="stBaseButton-primary"] > button:hover {{
    background: var(--sdb-primary-hover) !important;
    border-color: var(--sdb-primary-hover) !important;
    color: #FFFFFF !important;
  }}

  div[data-baseweb="select"] > div,
  div[data-baseweb="input"] > div,
  textarea,
  input {{
    border-radius: var(--sdb-radius) !important;
    border-color: var(--sdb-border) !important;
    background: var(--sdb-surface) !important;
  }}

  div[data-baseweb="select"] > div:focus-within,
  div[data-baseweb="input"] > div:focus-within,
  textarea:focus,
  input:focus {{
    border-color: var(--sdb-primary) !important;
    box-shadow: 0 0 0 2px rgba(47, 111, 104, 0.16) !important;
  }}

  div[data-testid="stTabs"] [role="tablist"] {{
    gap: 4px;
    border-bottom: 1px solid var(--sdb-border);
  }}

  div[data-testid="stTabs"] [role="tab"] {{
    color: var(--sdb-muted);
    font-weight: 700;
    padding: 8px 10px;
  }}

  div[data-testid="stTabs"] [aria-selected="true"] {{
    color: var(--sdb-primary);
  }}

  div[data-testid="stDataFrame"],
  div[data-testid="stTable"] {{
    border: 1px solid var(--sdb-border);
    border-radius: var(--sdb-radius);
    overflow: hidden;
    background: var(--sdb-surface);
    box-shadow: var(--sdb-shadow);
  }}

  .sdb-page-header,
  .explorer-header,
  .viewer-header {{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    border: 1px solid var(--sdb-border) !important;
    border-radius: var(--sdb-radius);
    background: linear-gradient(180deg, #FFFFFF 0%, #FBFAF7 100%);
    padding: 14px 16px !important;
    margin: 0 0 14px 0 !important;
    box-shadow: var(--sdb-shadow);
  }}

  .workbench-header {{
    border: 1px solid var(--sdb-border) !important;
    border-radius: var(--sdb-radius);
    background: linear-gradient(180deg, #FFFFFF 0%, #FBFAF7 100%);
    padding: 14px 16px !important;
    margin: 0 0 14px 0 !important;
    box-shadow: var(--sdb-shadow);
  }}

  .sdb-page-header h1 {{
    margin: 0 0 4px 0 !important;
    font-size: 28px !important;
  }}

  .sdb-page-header p {{
    margin: 0;
    font-size: 13px;
    color: var(--sdb-muted);
  }}

  .sdb-header-body {{
    flex: 1;
    min-width: 0;
  }}

  .sdb-eyebrow {{
    color: var(--sdb-primary-text);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: 5px;
  }}

  .sdb-header-chips {{
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
    max-width: 52%;
  }}

  .sdb-chip,
  .meta-chip,
  .status-ready,
  .status-later,
  .tag-chip,
  .risk-chip {{
    display: inline-flex;
    align-items: center;
    border-radius: 999px !important;
    border: 1px solid var(--sdb-border) !important;
    background: var(--sdb-surface-soft) !important;
    color: #344054 !important;
    font-size: 11px !important;
    font-weight: 800 !important;
    line-height: 1;
    padding: 5px 8px !important;
    margin: 2px 3px 2px 0;
    white-space: nowrap;
  }}

  .sdb-chip.primary {{
    border-color: var(--sdb-primary-border) !important;
    background: var(--sdb-primary-soft) !important;
    color: var(--sdb-primary-text) !important;
  }}

  .status-ready {{
    border-color: #BFD8CD !important;
    background: #EAF4EF !important;
    color: #1F5F53 !important;
  }}

  .home-card,
  .metric-card,
  .help-card,
  .catalog-card,
  .catalog-mini-metric,
  .matrix-summary-card,
  .step-card,
  .section-card,
  .compact-panel,
  .metric-row {{
    border: 1px solid var(--sdb-border) !important;
    border-radius: var(--sdb-radius) !important;
    background: var(--sdb-surface) !important;
    box-shadow: var(--sdb-shadow);
  }}

  .section-card {{
    padding: 10px !important;
  }}

  .detail-panel {{
    border: 1px solid var(--sdb-border) !important;
    border-radius: var(--sdb-radius);
    background: var(--sdb-surface) !important;
    box-shadow: var(--sdb-shadow);
    padding: 12px !important;
  }}

  .viewer-tab-link {{
    border-radius: var(--sdb-radius) !important;
    border-color: var(--sdb-border-strong) !important;
    background: var(--sdb-surface) !important;
    font-weight: 700 !important;
  }}

  .step-card:empty,
  .section-card:empty {{
    display: none !important;
  }}

  div[data-testid="stAlert"] {{
    border-radius: var(--sdb-radius) !important;
    border: 1px solid var(--sdb-border) !important;
  }}
</style>
""",
        unsafe_allow_html=True,
    )
    _inject_sidebar_toggle(sidebar_width=sidebar_width, logo_src=sidebar_logo_src)


def _asset_data_uri(path: Path) -> str:
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _inject_sidebar_toggle(*, sidebar_width: int, logo_src: str = "") -> None:
    """Add a persistent sidebar toggle because themed headers can hide Streamlit's native affordance."""

    toggle_script = """
<script>
(function () {
  const doc = window.parent && window.parent.document;
  if (!doc) return;
  const expandedWidth = "__SIDEBAR_WIDTH__";
  const sidebarLogoSrc = "__SIDEBAR_LOGO_SRC__";

  const existing = doc.getElementById("sdb-sidebar-toggle");
  const button = existing || doc.createElement("button");
  button.id = "sdb-sidebar-toggle";
  button.type = "button";
  button.title = "Toggle sidebar";
  button.setAttribute("aria-label", "Toggle sidebar");
  button.textContent = "Menu";
  button.style.position = "fixed";
  button.style.top = "14px";
  button.style.left = "14px";
  button.style.zIndex = "2147483647";
  button.style.minWidth = "54px";
  button.style.height = "30px";
  button.style.padding = "0 10px";
  button.style.border = "1px solid #CFC6BA";
  button.style.borderRadius = "8px";
  button.style.background = "#FFFFFF";
  button.style.color = "#174D47";
  button.style.font = "700 12px Inter, system-ui, sans-serif";
  button.style.boxShadow = "0 1px 2px rgba(16, 24, 40, 0.10)";
  button.style.cursor = "pointer";

  function findNativeSidebarToggle() {
    const buttons = Array.from(doc.querySelectorAll("button"));
    return buttons.find((candidate) => {
      if (candidate.id === "sdb-sidebar-toggle") return false;
      const text = (candidate.innerText || candidate.textContent || "").trim();
      const aria = candidate.getAttribute("aria-label") || "";
      const title = candidate.getAttribute("title") || "";
      return (
        text.includes("keyboard_double_arrow_left") ||
        text.includes("keyboard_double_arrow_right") ||
        /sidebar/i.test(aria) ||
        /sidebar/i.test(title)
      );
    });
  }

  function positionNativeSidebarToggle(expanded) {
    const nativeToggle = findNativeSidebarToggle();
    if (!nativeToggle) return;
    if (expanded) {
      const expandedPixels = parseInt(expandedWidth, 10) || 288;
      nativeToggle.style.position = "fixed";
      nativeToggle.style.top = "54px";
      nativeToggle.style.left = `${expandedPixels - 46}px`;
      nativeToggle.style.right = "auto";
      nativeToggle.style.zIndex = "2147483647";
      nativeToggle.style.display = "flex";
      nativeToggle.style.visibility = "visible";
      nativeToggle.style.opacity = "1";
    } else {
      nativeToggle.style.removeProperty("right");
      nativeToggle.style.removeProperty("left");
      nativeToggle.style.removeProperty("top");
    }
  }

  function syncSidebarLayout() {
    const sidebar = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sidebar) return;
    const expanded = sidebar.getAttribute("aria-expanded") !== "false";
    const inner = sidebar.firstElementChild;
    let brand = doc.getElementById("sdb-sidebar-brand");
    if (sidebarLogoSrc && !brand) {
      brand = doc.createElement("div");
      brand.id = "sdb-sidebar-brand";
      const image = doc.createElement("img");
      image.src = sidebarLogoSrc;
      image.alt = "ScenarioDB";
      brand.appendChild(image);
    }
    if (inner && brand && brand.parentElement !== inner) {
      inner.insertBefore(brand, inner.firstChild);
    }

    if (expanded) {
      sidebar.style.setProperty("width", expandedWidth, "important");
      sidebar.style.setProperty("min-width", expandedWidth, "important");
      sidebar.style.setProperty("max-width", expandedWidth, "important");
      sidebar.style.setProperty("flex-basis", expandedWidth, "important");
      sidebar.style.setProperty("flex-shrink", "0", "important");
      sidebar.style.setProperty("border-right", "1px solid #DED8CF", "important");
      sidebar.style.setProperty("background", "#F1EDE6", "important");
      sidebar.style.removeProperty("overflow");
      if (inner) {
        inner.style.setProperty("width", expandedWidth, "important");
        inner.style.setProperty("min-width", expandedWidth, "important");
        inner.style.setProperty("max-width", expandedWidth, "important");
        inner.style.setProperty("background", "#F1EDE6", "important");
        inner.style.removeProperty("padding-top");
      }
      if (brand) {
        brand.style.display = "flex";
        brand.style.position = "relative";
        brand.style.margin = "58px 14px 16px 14px";
        brand.style.width = "260px";
        brand.style.height = "196px";
        brand.style.zIndex = "1";
        brand.style.alignItems = "center";
        brand.style.justifyContent = "center";
        brand.style.overflow = "hidden";
        brand.style.pointerEvents = "none";
        brand.style.background = "transparent";
        const image = brand.querySelector("img");
        if (image) {
          image.style.width = "260px";
          image.style.maxWidth = "260px";
          image.style.height = "auto";
          image.style.maxHeight = "196px";
          image.style.objectFit = "contain";
          image.style.display = "block";
        }
      }
    } else {
      sidebar.style.setProperty("width", "0px", "important");
      sidebar.style.setProperty("min-width", "0px", "important");
      sidebar.style.setProperty("max-width", "0px", "important");
      sidebar.style.setProperty("flex-basis", "0px", "important");
      sidebar.style.setProperty("flex-shrink", "1", "important");
      sidebar.style.setProperty("border-right", "0", "important");
      sidebar.style.setProperty("overflow", "visible", "important");
      if (inner) {
        inner.style.setProperty("width", "0px", "important");
        inner.style.setProperty("min-width", "0px", "important");
        inner.style.setProperty("max-width", "0px", "important");
        inner.style.setProperty("overflow", "visible", "important");
        inner.style.removeProperty("padding-top");
      }
      if (brand) {
        brand.style.display = "none";
      }
    }
    positionNativeSidebarToggle(expanded);
  }

  button.onmouseenter = function () {
    button.style.background = "#E8F1EF";
    button.style.borderColor = "#B9D2CC";
  };
  button.onmouseleave = function () {
    button.style.background = "#FFFFFF";
    button.style.borderColor = "#CFC6BA";
  };
  button.onclick = function () {
    const nativeToggle = findNativeSidebarToggle();
    if (nativeToggle) nativeToggle.click();
    window.setTimeout(syncSidebarLayout, 50);
    window.setTimeout(syncSidebarLayout, 250);
    window.setTimeout(syncSidebarLayout, 700);
  };

  if (!existing) doc.body.appendChild(button);
  syncSidebarLayout();
  if (!window.__sdbSidebarLayoutObserver) {
    window.__sdbSidebarLayoutObserver = new MutationObserver(syncSidebarLayout);
    window.__sdbSidebarLayoutObserver.observe(doc.body, {
      attributes: true,
      childList: true,
      subtree: true,
      attributeFilter: ["aria-expanded", "style", "class"]
    });
  }
})();
</script>
""".replace("__SIDEBAR_WIDTH__", f"{sidebar_width}px").replace("__SIDEBAR_LOGO_SRC__", logo_src)

    components.html(
        toggle_script,
        height=0,
        width=0,
    )


def render_page_header(
    title: str,
    subtitle: str | None = None,
    *,
    eyebrow: str = "ScenarioDB",
    chips: Iterable[str] = (),
) -> None:
    """Render a consistent product-style page header."""

    chip_html = "".join(f'<span class="sdb-chip primary">{escape(str(chip))}</span>' for chip in chips)
    subtitle_html = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f"""
<div class="sdb-page-header">
  <div class="sdb-header-body">
    <div class="sdb-eyebrow">{escape(eyebrow)}</div>
    <h1>{escape(title)}</h1>
    {subtitle_html}
  </div>
  <div class="sdb-header-chips">{chip_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )
