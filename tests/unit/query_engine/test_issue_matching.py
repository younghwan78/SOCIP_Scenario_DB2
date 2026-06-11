from __future__ import annotations

from types import SimpleNamespace

from scenario_db.query_engine.service import _matched_issue_ids


def _variant(
    design_conditions: dict | None = None,
    sw_requirements: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="UHD60",
        design_conditions=design_conditions or {},
        ip_requirements={},
        sw_requirements=sw_requirements or {},
    )


def _scenario() -> SimpleNamespace:
    return SimpleNamespace(id="uc-camera")


def _issue(affects) -> SimpleNamespace:
    return SimpleNamespace(id="iss-llc-thrashing", affects=affects)


def _evidence(
    execution_context: dict | None = None,
    resolution_result: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="ev-latest",
        execution_context=execution_context or {},
        resolution_result=resolution_result or {},
    )


def test_canonical_list_affects_matches_via_match_rule():
    """Regression: canonical list-format affects must be evaluated, not skipped."""
    issue = _issue(
        [
            {
                "scenario_ref": "uc-camera",
                "match_rule": {
                    "all": [
                        {"axis": "resolution", "op": "in", "value": ["UHD", "8K"]},
                    ]
                },
            }
        ]
    )

    matched = _matched_issue_ids([issue], _scenario(), _variant({"resolution": "UHD"}))

    assert matched == ["iss-llc-thrashing"]


def test_canonical_list_affects_respects_match_rule_mismatch():
    issue = _issue(
        [
            {
                "scenario_ref": "uc-camera",
                "match_rule": {
                    "all": [
                        {"axis": "resolution", "op": "in", "value": ["UHD", "8K"]},
                    ]
                },
            }
        ]
    )

    assert _matched_issue_ids([issue], _scenario(), _variant({"resolution": "FHD"})) == []


def test_canonical_list_affects_scenario_ref_filter():
    issue = _issue([{"scenario_ref": "uc-other"}])

    assert _matched_issue_ids([issue], _scenario(), _variant()) == []


def test_canonical_list_affects_wildcard_and_missing_rule_match():
    wildcard = _issue([{"scenario_ref": "*"}])
    no_rule = _issue([{"scenario_ref": "uc-camera"}])

    assert _matched_issue_ids([wildcard], _scenario(), _variant()) == ["iss-llc-thrashing"]
    assert _matched_issue_ids([no_rule], _scenario(), _variant()) == ["iss-llc-thrashing"]


def test_canonical_list_affects_with_scope_section_like_demo_fixture():
    """Mirrors demo/fixtures/04_decision rule shape: scope + all sections."""
    issue = _issue(
        [
            {
                "scenario_ref": "uc-camera",
                "match_rule": {
                    "scope": {"project_ref": "*", "soc_ref": "soc-exynos2500"},
                    "all": [
                        {"axis": "resolution", "op": "in", "value": ["UHD", "8K"]},
                        {"axis": "thermal", "op": "in", "value": ["hot", "critical"]},
                    ],
                },
            }
        ]
    )

    matched = _matched_issue_ids(
        [issue],
        _scenario(),
        _variant({"resolution": "UHD", "thermal": "hot"}),
    )

    assert matched == ["iss-llc-thrashing"]


def test_malformed_match_rule_is_skipped_without_raising():
    issue = _issue(
        [
            {
                "scenario_ref": "uc-camera",
                "match_rule": {"axis": "resolution", "op": "bogus-op", "value": "UHD"},
            }
        ]
    )

    assert _matched_issue_ids([issue], _scenario(), _variant({"resolution": "UHD"})) == []


def test_malformed_regex_match_rule_is_skipped_without_raising():
    issue = _issue(
        [
            {
                "scenario_ref": "uc-camera",
                "match_rule": {"axis": "resolution", "op": "matches", "value": "["},
            }
        ]
    )

    assert _matched_issue_ids([issue], _scenario(), _variant({"resolution": "UHD"})) == []


def test_evidence_context_can_match_issue_like_review_gate():
    issue = _issue(
        [
            {
                "scenario_ref": "uc-camera",
                "match_rule": {
                    "all": [
                        {"axis": "resolution", "op": "eq", "value": "UHD"},
                        {"axis": "thermal", "op": "eq", "value": "hot"},
                        {
                            "sw_feature": "LLC_per_ip_partition",
                            "op": "eq",
                            "value": "disabled",
                        },
                    ]
                },
            }
        ]
    )
    variant = _variant(
        {"resolution": "UHD"},
        sw_requirements={
            "required_features": [{"LLC_per_ip_partition": "enabled"}],
        },
    )
    latest_evidence = _evidence(
        {"thermal": "hot"},
        {
            "sw_resolution": {
                "required_features_check": [
                    {
                        "feature": "LLC_per_ip_partition",
                        "actual": "disabled",
                        "status": "FAIL",
                    }
                ]
            }
        },
    )

    assert _matched_issue_ids([issue], _scenario(), variant) == []
    assert _matched_issue_ids([issue], _scenario(), variant, latest_evidence=latest_evidence) == [
        "iss-llc-thrashing"
    ]


def test_legacy_dict_affects_still_supported():
    issue = _issue({"scenario_ref": "uc-camera", "variant_ref": "UHD60"})
    other_variant = _issue({"scenario_ref": "uc-camera", "variant_ref": "FHD30"})

    assert _matched_issue_ids([issue], _scenario(), _variant()) == ["iss-llc-thrashing"]
    assert _matched_issue_ids([other_variant], _scenario(), _variant()) == []
