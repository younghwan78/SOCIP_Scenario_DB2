from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml
from streamlit.testing.v1 import AppTest

from dashboard.components.category_review import (
    CONDITION_HELP, SCENARIO_PURPOSES, condition_rows, guide_keys, scenario_purpose,
)

ROOT = Path(__file__).resolve().parents[3]


def item(project="project-a", **conditions):
    return {
        "soc_ref": "soc-exynos2600", "project_id": project,
        "scenario_id": "uc-game-play", "variant_id": "same-id",
        "category": ["game", "game"], "severity": "heavy",
        "design_conditions": conditions,
        "viewer_query": {"project_id": project, "scenario_id": "uc-game-play", "variant_id": "same-id"},
    }


def test_all_current_non_camera_fixtures_have_guidance_and_condition_help():
    seen = set()
    for path in (ROOT / "db_fixtures_Exynos2600_S26Plus/02_definition").glob("uc-*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        category = doc["metadata"]["category"]
        if "camera" in category:
            continue
        seen.add(doc["id"])
        for variant in doc["variants"]:
            row = {**item(), "scenario_id": doc["id"], "category": category,
                   "design_conditions": variant.get("design_conditions") or {}}
            assert guide_keys(row), path
            assert scenario_purpose(row) == SCENARIO_PURPOSES[doc["id"]]
            assert set(row["design_conditions"]) <= CONDITION_HELP.keys(), path
    assert seen == SCENARIO_PURPOSES.keys()


def test_guidance_does_not_infer_conditions_or_leak_soc_specific_scenario_text():
    row = item(camera_active=False, offload=False, bitrate_mbps=None)
    before = deepcopy(row)
    rows = {r["조건"]: r for r in condition_rows(row)}
    assert rows["camera_active"]["등록값"] == "False"
    assert rows["bitrate_mbps"]["등록값"] == "None"
    assert "fps" not in rows
    assert row == before
    assert scenario_purpose({**row, "soc_ref": "another-soc"}) != SCENARIO_PURPOSES["uc-game-play"]
    assert guide_keys({**row, "category": ["camera", "video"]}) == []
    assert guide_keys({**row, "category": ["voice_call", "video"]}) == ["voice_call"]
    assert guide_keys({**row, "category": ["new-category"]}) == []


def test_variant_selection_keeps_project_ownership_and_handles_empty_conditions():
    app = AppTest.from_string('''
import streamlit as st
from dashboard.components.category_review_view import render_category_matrix
render_category_matrix(st.session_state["items"])
''')
    app.session_state["items"] = [item(target_fps=60), item("project-b", target_fps=120)]
    app.run()
    assert not app.exception
    app.selectbox(key="category_review_variant").select(("project-b", "uc-game-play", "same-id")).run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["등록값"] == "120"
    app.session_state["items"] = [item("project-c")]
    app.run()
    assert not app.exception
    assert any("design_conditions가 없습니다" in e.value for e in app.info)
    app.session_state["items"] = []
    app.run()
    assert not app.exception
    assert not app.selectbox


def test_project_notice_and_partial_results_are_scoped():
    app = AppTest.from_string('''
import streamlit as st
from dashboard.components.category_review_view import render_project_context, render_category_overview
items = st.session_state["items"]
render_project_context(items, None)
render_category_overview(items, items, partial=True, categories=["game"])
''')
    app.session_state["items"] = [item(target_fps=60)]
    app.run()
    assert not app.exception
    assert any("M1S = Galaxy26, M2S = GalaxyS26+" in e.value for e in app.info)
    assert any("일부 API 결과" in e.value for e in app.warning)
    assert any("s5e9965-scaler.dtsi" in e.value for e in app.markdown)
    app.session_state["items"] = [{**item(), "soc_ref": "another-soc"}]
    app.run()
    assert not app.exception
    assert not app.info
    assert not any("s5e9965-scaler.dtsi" in e.value for e in app.markdown)
