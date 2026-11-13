"""Objective order of the recommendation: power only by default, robustness / IQ / BW first when asked."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_engine_equivalence import canonical_json  # noqa: E402
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import arch_exploration as ax  # noqa: E402
from scenario_db.sim.arch_exploration import ArchExplorationSpec, ExplorationObjective, explore_variant, input_hash  # noqa: E402
from scenario_db.sim.design_space import design_space_from_spec, spec_from_design_space  # noqa: E402
from scenario_db.sim.models import DVFSTable, SimulationRunConfig  # noqa: E402

VARIANT = "cam-rec-r1-uhd60-sdr"  # SW growth needs DVFS raises here: 1.0 -> 1.1 -> 1.2 cost power
AXES = {"statistics": ["max"], "runtime_scales": [1.0, 1.1, 1.2, 1.3], "dvfs_headroom_levels": 2,
        "power_options": {"enabled": False}}


@pytest.fixture(scope="module")
def graph():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    return graph_from_fixture(read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml"), VARIANT, catalog)


@pytest.fixture(scope="module")
def tables():
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


def _spec(**objective) -> ArchExplorationSpec:
    return ArchExplorationSpec.model_validate({"axes": AXES, "objective": objective, "verify": False})


def _run(graph, tables, **objective):
    return explore_variant(graph, _spec(**objective), config=SimulationRunConfig(), dvfs_tables=tables)


@pytest.fixture(scope="module")
def plain(graph, tables):
    return _run(graph, tables)


@pytest.fixture(scope="module")
def robust(graph, tables):
    return _run(graph, tables, order=["growth", "power"])


def test_the_default_objective_is_power_only_and_dumps_as_before(graph, tables, plain):
    assert ExplorationObjective().order == ["power"]
    assert ExplorationObjective().model_dump() == {"statistic": "max", "runtime_scale": 1.0, "tie_pct": 1.0}
    assert "objectives" not in plain and "growth_fixed" not in plain["recommended"]
    # writing the default order out changes neither the result nor the input hash
    explicit = _run(graph, tables, order=["power"])
    assert canonical_json(explicit) == canonical_json(plain)
    config = SimulationRunConfig()
    assert input_hash(graph, _spec(order=["power"]), config, tables) == input_hash(graph, _spec(), config, tables)
    # ... and a different order is part of what decides the result
    assert input_hash(graph, _spec(order=["growth", "power"]), config, tables) != input_hash(graph, _spec(), config, tables)


@pytest.mark.parametrize("objective, message", [
    ({"order": ["power", "power"]}, "twice"),
    ({"order": []}, "at least 1"),
    ({"order": ["speed"]}, "power"),
    ({"growth_target": 1.2}, "growth_target needs"),
    ({"order": ["growth"], "growth_target": 0.9}, "greater than or equal to 1"),
])
def test_invalid_objectives_are_refused(objective, message):
    with pytest.raises(ValueError, match=message):
        ExplorationObjective.model_validate(objective)


def test_growth_first_recommends_the_most_robust_case_and_says_what_it_costs(plain, robust):
    o = robust["objectives"]
    assert o["order"] == ["growth", "power"] and o["growth_target"] is None and o["target_met"] is None
    # the lowest-power case is still reported, and it is the case the default objective recommends
    assert o["min_power"]["key"] == plain["recommended"]["key"] and o["min_power"]["delta_mw"] == 0
    rec = robust["recommended"]
    assert rec["key"] == o["recommended"]["key"] and rec["growth_fixed"] == o["recommended"]["growth_fixed"]
    front = o["front"]
    # the front trades power for growth: both rise along it, it starts at the lowest-power case
    assert front[0]["key"] == o["min_power"]["key"]
    assert [p["growth_fixed"] for p in front] == sorted({p["growth_fixed"] for p in front})
    assert [p["total_mw"] for p in front] == sorted(p["total_mw"] for p in front)
    assert len(front) >= 2, "the sample DVFS ladder must give at least one robustness step on this variant"
    # most robust = the end of the front; it costs power and raises DVFS levels
    assert o["recommended"]["key"] == front[-1]["key"]
    assert o["recommended"]["growth_fixed"] > o["min_power"]["growth_fixed"]
    assert o["recommended"]["delta_mw"] > 0 and o["recommended"]["dvfs_raise"] > 0
    assert rec["total_mw"] == pytest.approx(plain["recommended"]["total_mw"] + o["recommended"]["delta_mw"], abs=0.02)
    # the robustness shown for the recommendation is the one the SW margin block reports
    assert robust["sw_margin"]["growth_tolerance_fixed"] == rec["growth_fixed"]


def test_a_growth_target_buys_just_enough_robustness(graph, tables, robust):
    front = robust["objectives"]["front"]
    target = front[1]["growth_fixed"]
    enough = _run(graph, tables, order=["growth", "power"], growth_target=target)["objectives"]
    assert enough["target_met"] is True and enough["recommended"]["key"] == front[1]["key"]
    # an unreachable target: the closest case is recommended and the miss is reported
    missed = _run(graph, tables, order=["growth", "power"], growth_target=9.0)["objectives"]
    assert missed["target_met"] is False and missed["recommended"]["key"] == front[-1]["key"]


def test_iq_first_keeps_image_quality_before_power(graph, tables, plain):
    out = _run(graph, tables, order=["iq", "power"])
    rec, o = out["recommended"], out["objectives"]
    assert o["recommended"]["iq_risk"] == min(ax._iq_risk(c) for c in [out["baseline"], *out["alternatives"], rec])
    assert not rec["lossy"] and o["recommended"]["iq_risk"] <= o["min_power"]["iq_risk"]
    assert rec["total_mw"] >= plain["recommended"]["total_mw"]


def test_bw_first_minimises_traffic(graph, tables, plain):
    out = _run(graph, tables, order=["bw", "power"])
    assert out["recommended"]["bw_mbs"] <= plain["recommended"]["bw_mbs"]
    assert out["objectives"]["recommended"]["bw_mbs"] == min(p["bw_mbs"] for p in [out["objectives"]["recommended"], out["objectives"]["min_power"]])


def test_only_the_recommendation_follows_the_order(plain, robust):
    # the case space, its distribution and the lever analysis inputs are the same; the order picks among them
    for key in ("counts", "distribution", "design_points", "slices", "buffers", "domains", "spec_ok"):
        assert canonical_json(robust[key]) == canonical_json(plain[key]), key
    # eligible cases only gain the robustness they were ranked by
    assert {k: v for k, v in robust["baseline"].items() if k != "growth_fixed"} == plain["baseline"]
    assert robust["tiers"]["keep"]["best"]["key"] == plain["tiers"]["keep"]["best"]["key"]


def test_rank_by_is_lexicographic_with_the_target_as_a_threshold():
    def case(key, mw, growth, lossy=False, comp=(), bw=100.0):
        return {"key": key, "total_mw": mw, "growth_fixed": growth, "lossy": lossy, "assumed_ratio": False,
                "compression": list(comp), "bw_mbs": bw, "dvfs_raise": 0}
    cases = [case("cheap", 100, 1.0), case("mid", 110, 1.2), case("robust", 130, 1.3), case("lossy", 90, 1.0, True, ("b",))]
    order = lambda **o: [c["key"] for c in ax._rank_by(cases, ExplorationObjective(**o))]  # noqa: E731
    assert order(order=["growth", "power"]) == ["robust", "mid", "lossy", "cheap"]
    assert order(order=["growth", "power"], growth_target=1.2) == ["mid", "robust", "lossy", "cheap"]
    assert order(order=["iq", "power"]) == ["cheap", "mid", "robust", "lossy"]
    assert order(order=["iq", "growth"]) == ["robust", "mid", "cheap", "lossy"]
    assert order(order=["power", "growth"]) == ["lossy", "cheap", "mid", "robust"]


def test_the_order_travels_through_the_design_space():
    spec = _spec(order=["growth", "iq", "power"], growth_target=1.2)
    space = design_space_from_spec(spec)
    assert space.objective.order == ["growth", "iq", "power"] and space.objective.growth_target == 1.2
    assert spec_from_design_space(space).model_dump(mode="json") == spec.model_dump(mode="json")
    assert "order" not in design_space_from_spec(_spec()).model_dump(mode="json")["objective"]
