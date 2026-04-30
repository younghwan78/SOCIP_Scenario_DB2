"""Import Workbench for ScenarioDB.

This page is intentionally a review/staging tool, not a direct DB editor.
It builds scenario.import_bundle payloads and calls the Write API flow:
stage -> validate -> diff -> apply.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.import_api_client import (
    ImportApiError,
    apply_batch,
    diff_batch,
    document_rows,
    health_check,
    import_report_rows,
    scenario_impact_rows,
    stage_import_bundle,
    validate_batch,
    validation_issue_rows,
)
from scenario_db.legacy_import.write_bundle import build_import_bundle_request


st.set_page_config(
    page_title="Import Workbench - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  .block-container {
    padding-top: 0.6rem !important;
    padding-left: 1.4rem !important;
    padding-right: 1.4rem !important;
    max-width: none !important;
  }
  header[data-testid="stHeader"], footer, #MainMenu { display: none !important; }
  section[data-testid="stSidebar"] { width: 300px !important; min-width: 300px !important; }
  section[data-testid="stSidebar"] > div { width: 300px !important; }
  .workbench-header {
    border-bottom: 1px solid #E8E4DF;
    padding-bottom: 12px;
    margin-bottom: 14px;
  }
  .workbench-title {
    font-size: 24px;
    font-weight: 850;
    color: #111827;
    margin-bottom: 4px;
  }
  .workbench-subtitle {
    color: #6B7280;
    font-size: 13px;
  }
  .step-card {
    border: 1px solid #E8E4DF;
    border-radius: 12px;
    background: #FFFFFF;
    padding: 14px 16px;
    margin: 12px 0;
  }
  .step-card h3 {
    margin: 0 0 8px 0;
    font-size: 15px;
    color: #111827;
  }
  .muted {
    color: #6B7280;
    font-size: 12px;
  }
  .danger-note {
    border-left: 3px solid #DC2626;
    background: #FEF2F2;
    padding: 8px 10px;
    border-radius: 7px;
    color: #7F1D1D;
    font-size: 12px;
  }
</style>
""",
    unsafe_allow_html=True,
)


def _state_default(key: str, value: Any) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


for _key, _value in {
    "import_bundle_payload": None,
    "import_bundle_issues": [],
    "import_bundle_path": "",
    "write_batch_id": "",
    "stage_result": None,
    "validation_result": None,
    "diff_result": None,
    "apply_result": None,
    "generated_dir_text": str(_root / "demo" / "generated" / "scenariodb"),
    "output_payload_text": str(_root / "demo" / "generated" / "scenariodb" / "import_bundle.json"),
    "dir_browser_root": str(_root / "demo"),
    "dir_browser_current": str(_root / "demo" / "generated"),
}.items():
    _state_default(_key, _value)


def _show_api_error(exc: ImportApiError) -> None:
    st.error(str(exc))
    if exc.status_code:
        st.caption(f"HTTP status: {exc.status_code}")
    if exc.body:
        st.code(exc.body, language="json")


def _save_payload(path_text: str, payload: dict[str, Any]) -> None:
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    st.session_state["import_bundle_path"] = str(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _render_directory_browser() -> None:
    st.markdown("#### Folder Browser")
    browser_root_text = st.text_input(
        "Browser root",
        key="dir_browser_root",
        help="Root directory visible in this server-side folder browser.",
    )
    root = Path(browser_root_text).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        st.warning("Browser root does not exist or is not a directory.")
        return

    current = Path(st.session_state.get("dir_browser_current") or root).expanduser().resolve()
    if not current.exists() or not current.is_dir() or not _is_relative_to(current, root):
        current = root
        st.session_state["dir_browser_current"] = str(current)

    nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 4])
    with nav_col1:
        if st.button("Root", key="dir_browser_root_btn"):
            st.session_state["dir_browser_current"] = str(root)
            st.rerun()
    with nav_col2:
        parent = current.parent
        can_go_up = current != root and _is_relative_to(parent, root)
        if st.button("Up", key="dir_browser_up_btn", disabled=not can_go_up):
            st.session_state["dir_browser_current"] = str(parent)
            st.rerun()
    with nav_col3:
        st.code(str(current), language="text")

    if st.button("Use this folder as generated directory", key="dir_browser_select_current", type="primary"):
        selected = str(current)
        st.session_state["generated_dir_text"] = selected
        st.session_state["output_payload_text"] = str(current / "import_bundle.json")
        st.rerun()

    try:
        children = sorted(
            [item for item in current.iterdir() if item.is_dir()],
            key=lambda item: item.name.lower(),
        )
    except OSError as exc:
        st.warning(f"Cannot list directory: {exc}")
        return

    if not children:
        st.caption("No subdirectories.")
        return

    st.caption(f"Subdirectories: {len(children)}")
    for index, child in enumerate(children[:80]):
        if not _is_relative_to(child, root):
            continue
        col_open, col_select, col_name = st.columns([1, 1, 5])
        with col_open:
            if st.button("Open", key=f"dir_browser_open_{index}_{child.name}"):
                st.session_state["dir_browser_current"] = str(child)
                st.rerun()
        with col_select:
            if st.button("Select", key=f"dir_browser_select_{index}_{child.name}"):
                st.session_state["generated_dir_text"] = str(child)
                st.session_state["output_payload_text"] = str(child / "import_bundle.json")
                st.rerun()
        with col_name:
            has_report = (child / "import_report.json").exists()
            marker = " import_report" if has_report else ""
            st.markdown(f"`{child.name}`{marker}")

    if len(children) > 80:
        st.caption("Showing first 80 subdirectories. Narrow the browser root if needed.")


with st.sidebar:
    st.markdown("### ScenarioDB Import")
    api_base = st.text_input(
        "API Base",
        value=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
    )
    actor = st.text_input("Actor", value="Joo Younghwan")
    note = st.text_input("Note", value="legacy import workbench")

    st.divider()
    if st.button("Check API", use_container_width=True):
        try:
            st.session_state["api_health"] = health_check(api_base)
            st.success("API reachable")
        except ImportApiError as exc:
            st.session_state["api_health"] = None
            _show_api_error(exc)

    st.caption("Set import paths in Step 1.")


st.markdown(
    """
<div class="workbench-header">
  <div class="workbench-title">Import Workbench</div>
  <div class="workbench-subtitle">
    Review legacy importer output and submit it through Write API staging.
    This page does not write DB rows directly.
  </div>
</div>
""",
    unsafe_allow_html=True,
)


with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown("### 1. Build Import Bundle")
    st.caption("Use an existing generated canonical YAML directory. Run legacy importer CLI first if this directory does not exist.")
    path_col1, path_col2 = st.columns([1, 1])
    with path_col1:
        generated_dir_text = st.text_input(
            "Generated canonical directory",
            key="generated_dir_text",
            help="Directory that contains 00_hw, 02_definition, and import_report.json.",
        )
    with path_col2:
        output_payload_text = st.text_input(
            "Bundle output JSON",
            key="output_payload_text",
            help="Optional JSON file path for the generated scenario.import_bundle request body.",
        )
    with st.expander("Browse folders", expanded=not Path(generated_dir_text).is_dir()):
        _render_directory_browser()
    generated_path = Path(generated_dir_text)
    status_col1, status_col2, status_col3 = st.columns(3)
    status_col1.metric("Generated dir", "exists" if generated_path.is_dir() else "missing")
    status_col2.metric("Import report", "exists" if (generated_path / "import_report.json").exists() else "missing")
    status_col3.metric("Output parent", "exists" if Path(output_payload_text).parent.exists() else "missing")
    col_a, col_b = st.columns([1, 1])
    with col_a:
        build_clicked = st.button("Build scenario.import_bundle", type="primary")
    with col_b:
        save_clicked = st.button("Save bundle JSON")

    if build_clicked:
        try:
            payload, issues = build_import_bundle_request(generated_path, actor=actor, note=note)
            st.session_state["import_bundle_payload"] = payload
            st.session_state["import_bundle_issues"] = issues
            st.session_state["stage_result"] = None
            st.session_state["validation_result"] = None
            st.session_state["diff_result"] = None
            st.session_state["apply_result"] = None
            st.success("Import bundle built")
        except Exception as exc:
            st.session_state["import_bundle_payload"] = None
            st.session_state["import_bundle_issues"] = [{"code": "bundle_build_failed", "message": str(exc), "source": generated_dir_text}]
            st.error(f"Bundle build failed: {exc}")

    payload = st.session_state["import_bundle_payload"]
    if save_clicked:
        if payload:
            _save_payload(output_payload_text, payload)
            st.success(f"Saved: {output_payload_text}")
        else:
            st.warning("Build a bundle before saving.")

    issues = st.session_state["import_bundle_issues"]
    if issues:
        st.warning("Bundle builder reported issues.")
        st.dataframe(issues, use_container_width=True, hide_index=True)

    if payload:
        report = (payload.get("payload") or {}).get("import_report") or {}
        documents = document_rows(payload)
        metric_cols = st.columns(4)
        metric_cols[0].metric("Import OK", str(report.get("ok")))
        metric_cols[1].metric("Documents", len(documents))
        metric_cols[2].metric("Messages", len(report.get("messages") or []))
        metric_cols[3].metric("Generated Keys", len(report.get("generated") or {}))

        st.markdown("#### Import Report Messages")
        rows = import_report_rows(report)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No import report messages.")

        st.markdown("#### Canonical Documents")
        if documents:
            st.dataframe(documents, use_container_width=True, hide_index=True)
        else:
            st.caption("No supported canonical documents in bundle.")

        with st.expander("Preview bundle JSON"):
            st.code(json.dumps(payload, indent=2, ensure_ascii=True), language="json")
    st.markdown("</div>", unsafe_allow_html=True)


with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown("### 2. Stage To Write API")
    payload = st.session_state["import_bundle_payload"]
    if st.button("Stage bundle", disabled=not bool(payload), use_container_width=True):
        try:
            result = stage_import_bundle(api_base, payload)
            st.session_state["stage_result"] = result
            st.session_state["write_batch_id"] = result.get("batch_id", "")
            st.session_state["validation_result"] = None
            st.session_state["diff_result"] = None
            st.session_state["apply_result"] = None
            st.success("Staged")
        except ImportApiError as exc:
            _show_api_error(exc)

    stage_result = st.session_state["stage_result"]
    if stage_result:
        st.json(stage_result)

    batch_id = st.text_input("Batch ID", value=st.session_state["write_batch_id"])
    st.session_state["write_batch_id"] = batch_id
    st.markdown("</div>", unsafe_allow_html=True)


with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown("### 3. Validate And Diff")
    batch_id = st.session_state["write_batch_id"]
    col_v, col_d = st.columns([1, 1])
    with col_v:
        if st.button("Validate batch", disabled=not bool(batch_id), use_container_width=True):
            try:
                st.session_state["validation_result"] = validate_batch(api_base, batch_id)
                st.success("Validation finished")
            except ImportApiError as exc:
                _show_api_error(exc)
    with col_d:
        validation = st.session_state["validation_result"]
        diff_disabled = not bool(batch_id) or not bool(validation and validation.get("valid"))
        if st.button("Preview diff", disabled=diff_disabled, use_container_width=True):
            try:
                st.session_state["diff_result"] = diff_batch(api_base, batch_id)
                st.success("Diff ready")
            except ImportApiError as exc:
                _show_api_error(exc)

    validation = st.session_state["validation_result"]
    if validation:
        valid = bool(validation.get("valid"))
        if valid:
            st.success("Validation valid")
        else:
            st.error("Validation failed")
        report_summary = validation.get("import_report")
        if report_summary:
            st.markdown("#### Write API Import Report Summary")
            st.json(report_summary)
        issues = validation_issue_rows(validation)
        if issues:
            st.markdown("#### Validation Issues")
            st.dataframe(issues, use_container_width=True, hide_index=True)

    diff = st.session_state["diff_result"]
    if diff:
        st.markdown("#### Diff Preview")
        st.json({"target_id": diff.get("target_id"), "operation": diff.get("operation")})
        changes = diff.get("changes") or []
        if changes:
            st.dataframe(changes, use_container_width=True, hide_index=True)
        impacts = scenario_impact_rows(diff)
        if impacts:
            st.markdown("#### Scenario Impact")
            st.dataframe(impacts, use_container_width=True, hide_index=True)
        with st.expander("Raw diff JSON"):
            st.code(json.dumps(diff, indent=2, ensure_ascii=True), language="json")
    st.markdown("</div>", unsafe_allow_html=True)


with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown("### 4. Apply")
    st.markdown(
        '<div class="danger-note">Apply writes canonical tables through Write API. '
        "Check validation and diff impact before continuing.</div>",
        unsafe_allow_html=True,
    )
    validation = st.session_state["validation_result"]
    diff = st.session_state["diff_result"]
    can_apply = bool(batch_id and validation and validation.get("valid") and diff)
    if st.button("Apply to DB", disabled=not can_apply, type="primary", use_container_width=True):
        try:
            st.session_state["apply_result"] = apply_batch(api_base, batch_id)
            st.success("Applied")
        except ImportApiError as exc:
            _show_api_error(exc)

    apply_result = st.session_state["apply_result"]
    if apply_result:
        st.json(apply_result)
        applied_refs = apply_result.get("applied_refs") or {}
        scenario_refs = applied_refs.get("scenario_refs") or []
        if scenario_refs:
            st.caption("Applied scenario refs:")
            st.code("\n".join(scenario_refs))
    st.markdown("</div>", unsafe_allow_html=True)
