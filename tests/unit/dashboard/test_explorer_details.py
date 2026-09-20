from __future__ import annotations

from copy import deepcopy

import pytest
from streamlit.testing.v1 import AppTest

from dashboard.components import explorer_details as details
from dashboard.components.viewer_api_client import ViewerApiError


def variant(project, identity, conditions, scenario="scene"):
    return {"project_id": project, "scenario_id": scenario, "variant_id": identity,
            "design_conditions": conditions}


def test_conditions_compare_within_owner_and_preserve_missing_false_and_types():
    items = [variant("p1", "b", {"fps": 60, "offload": False, "extra": None}),
             variant("p1", "a", {"fps": 30, "offload": False, "removed": 1}),
             variant("p2", "a", {"fps": 120}),
             variant("p1", "a", {"fps": 24}, scenario="another")]
    before = deepcopy(items)
    rows = details.condition_differences(items)
    changed = {key for key, _, diff in rows[0]["conditions"] if diff}
    assert changed == {"fps", "removed", "extra"}
    assert rows[0]["baseline"] == "a"
    assert all(not diff for row in rows[1:] for _, _, diff in row["conditions"])
    assert items == before
    typed = details.condition_differences([variant("p", "a", {"x": False}), variant("p", "b", {"x": 0})])
    assert typed[1]["conditions"][0][2]


def test_condition_html_escapes_values_and_marks_changes_beyond_seven_fields():
    base = {f"key{i}": i for i in range(10)}
    html = details.condition_table_html([
        variant("<script>", "a", base),
        variant("<script>", "b", {**base, "key9": "<img src=x onerror=alert(1)>"}),
    ])
    assert "<script>" not in html
    assert "<img" not in html
    assert "Δ key9=" in html
    assert "차이 1개" in html
    assert "&lt;img" in html


@pytest.mark.parametrize("kind,endpoint", [("sensor", "ip-catalogs"), ("display", "ip-catalogs"), ("sw_profile", "sw-profiles")])
def test_reference_lookup_uses_exact_reference(monkeypatch, kind, endpoint):
    calls = []
    def request(*args):
        calls.append(args)
        return {"id": "ip one"}
    monkeypatch.setattr(details, "_request_json", request)
    details.get_reference("api", kind, "ip one")
    assert calls == [("GET", "api", f"/{endpoint}/ip%20one")]


def test_reference_popup_is_lazy_and_uses_selected_project(monkeypatch):
    calls = []
    def lookup(api, kind, ref):
        calls.append((kind, ref))
        return {"id": ref, "category": "sensor", "capabilities": {"resolution": "test-mode"}}
    monkeypatch.setattr(details, "get_reference", lookup)
    app = AppTest.from_string('''
import streamlit as st
from dashboard.components.explorer_details import render_catalog_references
render_catalog_references("api", st.session_state["items"])
''')
    app.session_state["items"] = [
        {"project_id": "p1", "scenario_id": "same", "sensor_module_ref": "sensor-a"},
        {"project_id": "p2", "scenario_id": "same", "sensor_module_ref": "sensor-b"},
    ]
    app.run()
    assert not app.exception
    assert calls == []
    assert app.button(key="catalog_reference_display").disabled
    app.selectbox(key="catalog_reference_scenario").select(("p2", "same")).run()
    app.button(key="catalog_reference_sensor").click().run()
    assert not app.exception
    assert calls == [("sensor", "sensor-b")]
    assert any("p2 / sensor-b" in element.value for element in app.text)
    assert any("test-mode" in element.value for element in app.json)


def test_reference_popup_handles_api_failure(monkeypatch):
    def fail(*args):
        raise ViewerApiError("missing", status_code=404)
    monkeypatch.setattr(details, "get_reference", fail)
    app = AppTest.from_string('''
from dashboard.components.explorer_details import reference_dialog
reference_dialog("api", "display", "missing", "p")
''').run()
    assert not app.exception
    assert any("상세 정보를 불러오지 못했습니다" in element.value for element in app.error)
