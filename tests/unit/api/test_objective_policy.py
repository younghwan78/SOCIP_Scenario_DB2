"""The project review policy can set what the exploration recommendation prefers; a request can override it."""
from __future__ import annotations

import pytest

from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
from scenario_db.api.services.recompute import variant_spec
from scenario_db.api.services.review_policy import apply_objective
from scenario_db.models.definition.project import ReviewPolicy
from scenario_db.sim.arch_exploration import ExplorationObjective


def _objective(**fields) -> ExplorationObjective:
    return ArchExplorationRunRequest.model_validate({"scenario_ids": ["uc-a"], "spec": {"objective": fields}}).spec.objective


def test_no_policy_or_no_order_keeps_the_lowest_power_recommendation():
    objective = _objective()
    assert apply_objective(objective, None) is objective
    assert apply_objective(objective, ReviewPolicy()) is objective
    assert apply_objective(objective, ReviewPolicy(sw_growth_budget=1.2)) is objective  # a budget alone changes nothing


def test_the_policy_order_applies_with_the_growth_budget_as_the_target():
    policy = ReviewPolicy(objective_order=["growth", "power"], sw_growth_budget=1.2)
    applied = apply_objective(_objective(statistic="mean", runtime_scale=1.1), policy)
    assert applied.order == ["growth", "power"] and applied.growth_target == 1.2
    assert applied.statistic == "mean" and applied.runtime_scale == 1.1
    # no budget, or a budget of x1.0 (none declared): the most robust case, no target
    assert apply_objective(_objective(), ReviewPolicy(objective_order=["growth", "power"])).growth_target is None
    assert apply_objective(_objective(), ReviewPolicy(objective_order=["growth"], sw_growth_budget=1.0)).growth_target is None
    # an order without growth takes no target
    kept = apply_objective(_objective(), ReviewPolicy(objective_order=["iq", "power"], sw_growth_budget=1.3))
    assert kept.order == ["iq", "power"] and kept.growth_target is None


def test_a_request_that_sets_the_order_wins_over_the_policy():
    policy = ReviewPolicy(objective_order=["growth", "power"], sw_growth_budget=1.2)
    for fields in ({"order": ["power"]}, {"order": ["iq", "power"]}, {"order": ["growth"], "growth_target": 1.5}):
        objective = _objective(**fields)
        assert apply_objective(objective, policy) is objective
    # a request that only sets its own target keeps it under the policy order
    own = apply_objective(ExplorationObjective.model_validate({"order": ["growth", "power"], "growth_target": 1.5}), policy)
    assert own.growth_target == 1.5


def test_the_resolved_order_is_stored_so_a_recomputation_keeps_it():
    applied = apply_objective(_objective(), ReviewPolicy(objective_order=["growth", "power"], sw_growth_budget=1.2))
    stored = {"objective": applied.model_dump(mode="json"), "axes": {}}
    assert stored["objective"]["order"] == ["growth", "power"] and stored["objective"]["growth_target"] == 1.2
    again = ArchExplorationRunRequest.model_validate({"scenario_ids": ["uc-a"], "spec": variant_spec(stored)}).spec.objective
    assert again.order == ["growth", "power"] and again.growth_target == 1.2
    # re-applying the policy to the stored, explicit order is a no-op even if the policy moved on
    assert apply_objective(again, ReviewPolicy(objective_order=["iq", "power"])) is again


@pytest.mark.parametrize("order", [["power", "power"], [], ["speed"]])
def test_the_policy_validates_its_order(order):
    with pytest.raises(ValueError):
        policy = ReviewPolicy(objective_order=order)
        apply_objective(_objective(), policy)
