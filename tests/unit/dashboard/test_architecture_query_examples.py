from __future__ import annotations

from dashboard.components.query_examples import (
    EXAMPLE_CASES,
    apply_example_to_state,
    predicate_rows_for_editor,
    summarize_query_results,
)


def test_frequent_query_cases_match_architecture_exploration_shortcuts() -> None:
    assert [item["id"] for item in EXAMPLE_CASES] == [
        "sbwc_buffers",
        "llc_usage",
        "camera_power_threshold",
        "camera_npu_usage",
        "camera_gpu_usage",
    ]
    assert [item["title"] for item in EXAMPLE_CASES] == [
        "SBWC 사용",
        "LLC 사용",
        "Camera power 기준 이상",
        "Camera NPU 사용",
        "Camera GPU 사용",
    ]


def test_frequent_query_cases_use_specific_ip_and_camera_filters() -> None:
    cases = {item["id"]: item for item in EXAMPLE_CASES}

    assert cases["llc_usage"]["predicates"] == [
        {"field": "topology.uses_ip", "op": "contains", "value": "llc"},
    ]
    assert cases["camera_power_threshold"]["predicates"] == [
        {"field": "scenario.category", "op": "eq", "value": "camera"},
        {"field": "evidence.latest.kpi.total_power_mw", "op": "gte", "value": "100"},
        {"field": "evidence.latest.feasibility", "op": "exists", "value": True},
    ]
    assert cases["camera_npu_usage"]["predicates"] == [
        {"field": "scenario.category", "op": "eq", "value": "camera"},
        {"field": "topology.uses_ip", "op": "contains", "value": "npu"},
    ]
    assert cases["camera_gpu_usage"]["predicates"] == [
        {"field": "scenario.category", "op": "eq", "value": "camera"},
        {"field": "topology.uses_ip", "op": "contains", "value": "gpu"},
    ]


def test_apply_example_preserves_current_scope_when_case_has_no_scope() -> None:
    state = {
        "query_soc_ref": "soc-exynos2600",
        "query_project_ref": "proj-sm-s947b",
        "query_scenario_id": "",
        "query_variant_id": "",
        "query_predicate_rows": [],
    }
    case = next(item for item in EXAMPLE_CASES if item["id"] == "sbwc_buffers")

    updated = apply_example_to_state(state, case)

    assert updated["query_soc_ref"] == "soc-exynos2600"
    assert updated["query_project_ref"] == "proj-sm-s947b"
    assert updated["query_scenario_id"] == ""
    assert updated["query_variant_id"] == ""
    assert updated["query_predicate_rows"] == case["predicates"]


def test_predicate_rows_for_editor_stringifies_values_for_editable_value_cells() -> None:
    rows = [
        {"field": "scenario.category", "op": "eq", "value": "camera"},
        {"field": "evidence.latest.kpi.total_power_mw", "op": "gte", "value": 100},
        {"field": "evidence.latest.feasibility", "op": "exists", "value": True},
        {"field": "topology.uses_ip", "op": "contains", "value": None},
    ]

    assert predicate_rows_for_editor(rows) == [
        {"field": "scenario.category", "op": "eq", "value": "camera"},
        {"field": "evidence.latest.kpi.total_power_mw", "op": "gte", "value": "100"},
        {"field": "evidence.latest.feasibility", "op": "exists", "value": "True"},
        {"field": "topology.uses_ip", "op": "contains", "value": ""},
    ]


def test_apply_example_overrides_only_scope_keys_declared_by_case() -> None:
    state = {
        "query_soc_ref": "soc-exynos2600",
        "query_project_ref": "proj-sm-s947b",
        "query_scenario_id": "",
        "query_variant_id": "",
        "query_predicate_editor_version": 4,
        "query_predicate_rows": [],
    }
    case = {
        "scope": {"scenario_id": "uc-camera-recording"},
        "predicates": [{"field": "scenario.category", "op": "eq", "value": "camera"}],
    }

    updated = apply_example_to_state(state, case)

    assert updated["query_soc_ref"] == "soc-exynos2600"
    assert updated["query_project_ref"] == "proj-sm-s947b"
    assert updated["query_scenario_id"] == "uc-camera-recording"
    assert updated["query_variant_id"] == ""
    assert updated["query_predicate_editor_version"] == 5
    assert updated["query_predicate_rows"] == case["predicates"]


def test_query_result_summary_counts_scenarios_and_variants() -> None:
    items = [
        {"scenario_id": "uc-camera", "variant_id": "a", "category": ["camera"]},
        {"scenario_id": "uc-camera", "variant_id": "b", "category": ["camera"]},
        {"scenario_id": "uc-video", "variant_id": "a", "category": ["video"]},
    ]

    summary = summarize_query_results(items)

    assert summary == {
        "scenario_count": 2,
        "variant_count": 3,
        "category_count": 2,
        "top_scenarios": "uc-camera:2, uc-video:1",
    }
