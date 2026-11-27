"""R-2 knob constraints: valid combinations checked by compile, the strict ETL, the Write API and What-if."""

from copy import deepcopy

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.authoring.knobs import constraint_violations
from scenario_db.authoring.scenario import power_options_doc
from scenario_db.models.definition.usecase import PowerOptionSpec
from scenario_db.sim.judgement import constraint_issues

RULES = [
    {"id": "big-needs-full", "when": {"size": ["200m", "50m"]}, "require": {"readout": "full"}, "reason": "mode change"},
    {"id": "raw-no-readout", "when": {"format": "raw"}, "require": {"readout": None}},
    {"id": "npu-ai", "when_node_enabled": "npu", "when": {"ai": True}, "require": {"size": ["200m"]}},
]


def _v(**design):
    return {"design_conditions": design, "routing_switch": {}}


def test_a_rule_applies_on_when_and_checks_every_require_key():
    assert constraint_violations(RULES, _v(size="200m", readout="full")) == []
    assert constraint_violations(RULES, _v(size="12m")) == []                     # when does not match
    [msg] = constraint_violations(RULES, _v(size="50m", readout="binning"))
    assert msg == "constraint big-needs-full: {'readout': 'binning'} must be {'readout': 'full'} (mode change)"
    assert constraint_violations(RULES, _v(format="raw")) == []                   # null = absent
    assert constraint_violations(RULES, _v(format="raw", readout="full"))         # present breaks it


def test_when_node_enabled_limits_a_rule():
    v = _v(ai=True, size="12m")
    assert constraint_violations(RULES, v)
    v["routing_switch"] = {"disabled_nodes": ["npu"]}
    assert constraint_violations(RULES, v) == []


def test_the_schema_refuses_duplicate_ids_and_an_empty_require():
    with pytest.raises(ValidationError, match="duplicate"):
        PowerOptionSpec.model_validate({"constraints": [RULES[0], RULES[0]]})
    with pytest.raises(ValidationError):
        PowerOptionSpec.model_validate({"constraints": [{"id": "x", "when": {}, "require": {}}]})
    assert PowerOptionSpec.model_validate({}).constraints is None


def test_constraints_are_exported_without_knobs():
    assert power_options_doc({"constraints": RULES[:1]}) == {"constraints": RULES[:1]}
    assert power_options_doc({"params": {"a": 1}}) == {"params": {"a": 1}}       # unchanged without constraints


def test_constraint_issues_resolve_inheritance():
    variants = [{"id": "base", "design_conditions": {"size": "200m", "readout": "full"}},
                {"id": "child", "derived_from_variant": "base", "design_conditions_override": {"readout": "binning"}}]
    errors = constraint_issues("uc", {"constraints": RULES}, variants)
    assert errors == ["uc/child: constraint big-needs-full: {'readout': 'binning'} must be {'readout': 'full'} "
                      "(mode change)"]
    assert constraint_issues("uc", {"params": {}}, variants) == []                 # nothing declared


def _capture():
    with open("db_Exynos2600_SM-S947B/02_definition/uc-cam-capture-e2600.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_e2600_capture_variants_keep_the_declared_combinations():
    doc = _capture()
    assert {c["id"] for c in doc["power_options"]["constraints"]} >= {"remosaic-needs-full-readout", "raw-is-12m"}
    assert constraint_issues(doc["id"], doc["power_options"], doc["variants"]) == []
    broken = deepcopy(doc["variants"])
    v = next(x for x in broken if x["id"] == "cam-cap-r1-remosaic-mf")
    v["design_conditions"].pop("capture_readout")
    [error] = constraint_issues(doc["id"], doc["power_options"], broken)
    assert error.startswith("uc-cam-capture-e2600/cam-cap-r1-remosaic-mf: constraint remosaic-needs-full-readout")


def test_the_write_api_reports_a_broken_constraint_on_the_staged_variant():
    from scenario_db.write.service import _constraint_write_issues

    variants = [{"id": "a", "design_conditions": {"size": "200m", "readout": "full"}},
                {"id": "b", "design_conditions": {"size": "200m"}}]
    issues = _constraint_write_issues("uc", {"constraints": RULES}, variants, "payload.variant", only={"b"})
    assert [(i.severity, i.code) for i in issues] == [("error", "knob_constraint_violated")]
    assert _constraint_write_issues("uc", {"constraints": RULES}, variants, "payload.variant", only={"a"}) == []


def test_a_what_if_condition_may_not_leave_the_valid_combinations():
    from scenario_db.api.services.whatif_conditions import apply_whatif_changes
    from scenario_db.sim.models import SimulationRunConfig
    from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

    graph = _exynos2600_generated_graph("uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis")
    apply_whatif_changes(graph, [{"target": "fps", "value": 60}], SimulationRunConfig())          # no rule: ok
    graph.scenario.power_options = {**(graph.scenario.power_options or {}), "constraints": [
        {"id": "uhd-30-only", "when": {"fps": 60}, "require": {"fps": [30]}}]}
    with pytest.raises(ValueError, match="breaks a knob constraint: constraint uhd-30-only"):
        apply_whatif_changes(graph, [{"target": "fps", "value": 60}], SimulationRunConfig())
