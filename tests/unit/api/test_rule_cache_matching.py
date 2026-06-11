from __future__ import annotations

from types import SimpleNamespace

from scenario_db.api.cache import match_issues_for_variant
from scenario_db.matcher.context import MatcherContext


def _ctx(design_conditions: dict | None = None) -> MatcherContext:
    return MatcherContext(
        design_conditions=design_conditions or {"resolution": "UHD"},
        ip_requirements={},
        sw_requirements={},
    )


def _issue(issue_id: str, affects) -> SimpleNamespace:
    return SimpleNamespace(id=issue_id, affects=affects)


def _good_issue(issue_id: str = "iss-good") -> SimpleNamespace:
    return _issue(
        issue_id,
        [
            {
                "scenario_ref": "*",
                "match_rule": {"axis": "resolution", "op": "eq", "value": "UHD"},
            }
        ],
    )


def _malformed_issue(issue_id: str = "iss-broken") -> SimpleNamespace:
    return _issue(
        issue_id,
        [
            {
                "scenario_ref": "*",
                "match_rule": {"axis": "resolution", "op": "bogus-op", "value": "UHD"},
            }
        ],
    )


def test_malformed_rule_is_isolated_and_reported():
    """Regression: one malformed match_rule must not 500 the whole matched-issues
    response; the failing issue id is surfaced via evaluation_errors."""
    errors: list[str] = []

    matched = match_issues_for_variant(
        _ctx(),
        [_malformed_issue(), _good_issue()],
        evaluation_errors=errors,
    )

    assert [m.id for m in matched] == ["iss-good"]
    assert errors == ["iss-broken"]


def test_malformed_rule_does_not_raise_without_error_collector():
    matched = match_issues_for_variant(_ctx(), [_malformed_issue()])

    assert matched == []


def test_error_collector_records_each_issue_once():
    errors: list[str] = []
    issue = _issue(
        "iss-broken",
        [
            {"scenario_ref": "*", "match_rule": {"axis": "a", "op": "bogus-op", "value": 1}},
            {"scenario_ref": "*", "match_rule": {"axis": "b", "op": "bogus-op", "value": 2}},
        ],
    )

    match_issues_for_variant(_ctx(), [issue], evaluation_errors=errors)

    assert errors == ["iss-broken"]


def test_later_affect_entry_can_still_match_after_failure():
    errors: list[str] = []
    issue = _issue(
        "iss-mixed",
        [
            {"scenario_ref": "*", "match_rule": {"axis": "resolution", "op": "bogus-op", "value": "UHD"}},
            {"scenario_ref": "*", "match_rule": {"axis": "resolution", "op": "eq", "value": "UHD"}},
        ],
    )

    matched = match_issues_for_variant(_ctx(), [issue], evaluation_errors=errors)

    assert [m.id for m in matched] == ["iss-mixed"]
    assert errors == ["iss-mixed"]
