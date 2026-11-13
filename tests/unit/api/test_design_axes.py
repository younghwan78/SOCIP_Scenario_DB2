"""Re-simulation lever axes: What-if change kinds explored as changed variants."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_engine_equivalence import canonical_json  # noqa: E402
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest  # noqa: E402
from scenario_db.api.services import analysis_inputs, whatif_sensors  # noqa: E402
from scenario_db.api.services import arch_exploration as svc  # noqa: E402
from scenario_db.api.services.design_axes import (  # noqa: E402
    EXPLORABLE_KINDS,
    axis_changes,
    build_design_plan,
    explore_with_levers,
    validate_levers,
)
from scenario_db.api.services.recompute import variant_spec  # noqa: E402
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, apply_whatif_changes  # noqa: E402
from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim.arch_exploration import ArchExplorationSpec, LeverAxis, explore_variant, input_hash  # noqa: E402
from scenario_db.sim.models import SimulationRunConfig  # noqa: E402

VARIANT = "cam-rec-r1-uhd30-vdis"
NARROW = {"statistics": ["max"], "runtime_scales": [1.0], "power_options": {"enabled": False}}
LEVERS = [
    {"lever": "fps", "values": [24, 60]},
    {"lever": "llc_alloc", "params": {"buffer_id": "PYRAMID_L0"}, "values": ["off"]},
]


@pytest.fixture(scope="module")
def graph():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    return graph_from_fixture(read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml"), VARIANT, catalog)


def _spec(levers=None, **axes) -> ArchExplorationSpec:
    return ArchExplorationSpec.model_validate({"axes": NARROW | axes | ({"levers": levers} if levers else {}), "verify": False})


@pytest.fixture(scope="module")
def explored(graph):
    return explore_with_levers(graph, _spec(LEVERS), config=SimulationRunConfig(), dvfs_tables={})


def test_explorable_kinds_are_registered_change_kinds():
    assert set(EXPLORABLE_KINDS) <= set(CHANGE_KINDS)
    # searched per case by a built-in lever, outside the model, or prepared per request
    assert set(CHANGE_KINDS) - set(EXPLORABLE_KINDS) == {"compression", "dvfs_level", "node_param", "sensor_binding"}


@pytest.mark.parametrize("axis, changes", [
    ({"lever": "fps", "values": [24, 60.0]}, [{"target": "fps", "value": 24.0}, {"target": "fps", "value": 60.0}]),
    ({"lever": "chain_size", "params": {"node_id": "byrp"}, "values": [[3840, 2160], {"width": 1920, "height": 1080, "operation": "scale"}]},
     [{"target": "chain_size", "node_id": "byrp", "width": 3840, "height": 2160},
      {"target": "chain_size", "node_id": "byrp", "width": 1920, "height": 1080, "operation": "scale"}]),
    ({"lever": "llc_alloc", "params": {"buffer_id": "B"}, "values": ["off", {"option": "on", "value": 0.5}]},
     [{"target": "llc_alloc", "buffer_id": "B", "option": "off"}, {"target": "llc_alloc", "buffer_id": "B", "option": "on", "value": 0.5}]),
    ({"lever": "power_knob", "params": {"param": "pyramid_l0"}, "values": ["skip"]},
     [{"target": "power_knob", "param": "pyramid_l0", "option": "skip"}]),
])
def test_axis_values_become_whatif_changes(axis, changes):
    assert axis_changes(LeverAxis.model_validate(axis)) == changes


def test_every_combination_that_changes_a_lever_is_explored(explored):
    design = explored["design_axes"]
    assert design["status"] == "ok" and design["sets"] == 5 and not design["errors"]
    assert [d["label"] for d in design["dimensions"]] == ["FPS", "LLC 할당 · PYRAMID_L0"]
    assert design["dimensions"][0]["values"] == ["24 fps", "60 fps"]
    rows = {r["key"]: r for r in design["results"]}
    assert set(rows) == {"fps=24", "fps=60", "llc_alloc[PYRAMID_L0]=off", "fps=24 | llc_alloc[PYRAMID_L0]=off",
                         "fps=60 | llc_alloc[PYRAMID_L0]=off"}
    assert rows["fps=24"]["fps"] == 24.0 and rows["fps=60"]["fps"] == 60.0 and rows["llc_alloc[PYRAMID_L0]=off"]["fps"] == 30.0
    # compared with the variant itself; lower fps = less power, LLC off = more DRAM traffic
    assert rows["fps=24"]["delta_mw"] < 0 < rows["llc_alloc[PYRAMID_L0]=off"]["delta_mw"]
    assert rows["fps=24"]["total_mw"] == pytest.approx(explored["recommended"]["total_mw"] + rows["fps=24"]["delta_mw"], abs=1e-2)
    assert rows["llc_alloc[PYRAMID_L0]=off"]["raw_delta_mw"] > 0
    assert rows["fps=24 | llc_alloc[PYRAMID_L0]=off"]["labels"] == ["FPS 24 fps", "LLC 할당 · PYRAMID_L0 off"]
    # ordered: spec OK first, then by power; nothing is recommended
    ok = [r["spec_ok"] for r in design["results"]]
    assert ok == sorted(ok, reverse=True) and "best" not in design
    assert explored["counts"]["design_cases"] == design["cases"] > 0


def test_a_combination_row_equals_exploring_that_changed_variant(graph, explored):
    config = SimulationRunConfig()
    changed, cfg, _ = apply_whatif_changes(graph, [{"target": "fps", "value": 24}], config, None)
    alone = explore_variant(changed, _spec(), config=cfg)
    row = next(r for r in explored["design_axes"]["results"] if r["key"] == "fps=24")
    assert row["total_mw"] == round(alone["recommended"]["total_mw"], 3)
    assert row["case_key"] == alone["recommended"]["key"] and row["spec_ok"] == alone["spec_ok"]
    assert row["raw_total_mw"] == round(alone["baseline"]["total_mw"], 3)


def test_the_variant_itself_is_unchanged_by_lever_axes(graph, explored):
    config = SimulationRunConfig()
    plain = explore_variant(graph, _spec(), config=config)
    own = {k: v for k, v in explored.items() if k != "design_axes"}
    own["counts"] = {k: v for k, v in own["counts"].items() if k != "design_cases"}
    assert canonical_json(own) == canonical_json(plain)
    # ... including the input hash: a prediction of this variant does not depend on the lever axes
    assert input_hash(graph, _spec(LEVERS), config, {}) == input_hash(graph, _spec(), config, {})
    assert explored["input_hash"] == plain["input_hash"]


def test_a_lever_this_variant_does_not_have_is_an_error_row_not_a_failure(graph):
    levers = [*LEVERS, {"lever": "chain_size", "params": {"node_id": "no_such_node"}, "values": [[1920, 1080]]}]
    summary = explore_with_levers(graph, _spec(levers), config=SimulationRunConfig(), dvfs_tables={})
    design = summary["design_axes"]
    assert design["sets"] == 11 and len(design["results"]) == 5 and len(design["errors"]) == 6
    assert all("no_such_node" in e["key"] and "no_such_node" in e["error"] for e in design["errors"])
    only = explore_with_levers(graph, _spec([levers[-1]]), config=SimulationRunConfig(), dvfs_tables={})
    assert only["design_axes"]["status"] == "failed" and only["spec_ok"] is summary["spec_ok"]


def test_plan_marks_iq_and_keeps_the_loaded_graph_untouched(graph):
    before = canonical_json({"variant": graph.variant.node_configs, "design": graph.variant.design_conditions,
                             "buffers": graph.variant.buffer_overrides})
    plan = build_design_plan(graph, SimulationRunConfig(), [
        LeverAxis(lever="power_knob", params={"param": "pyramid_l0"}, values=["skip"]), LeverAxis(lever="fps", values=[24])])
    by_key = {s["key"]: s for s in plan["sets"]}
    assert set(by_key) == {"fps=24", "power_knob[pyramid_l0]=skip", "power_knob[pyramid_l0]=skip | fps=24"}
    assert by_key["fps=24"]["iq"] == "neutral" and by_key["power_knob[pyramid_l0]=skip"]["iq"] == "eval"
    assert by_key["power_knob[pyramid_l0]=skip | fps=24"]["iq"] == "eval"
    assert all("graph" in s and s["graph"] is not graph for s in plan["sets"])
    assert before == canonical_json({"variant": graph.variant.node_configs, "design": graph.variant.design_conditions,
                                     "buffers": graph.variant.buffer_overrides})


def test_the_engine_needs_the_prepared_plan_and_the_case_budget_holds(graph):
    config = SimulationRunConfig()
    with pytest.raises(ValueError, match="prepared design sets"):
        explore_variant(graph, _spec(LEVERS), config=config)
    plain = explore_variant(graph, _spec(), config=config)
    full = explore_with_levers(graph, _spec(LEVERS), config=config, dvfs_tables={})
    own, extra = plain["counts"]["cases"], full["counts"]["design_cases"]
    assert svc._cases_used(full) == own + extra
    # the variant's cases come first; the lever combinations get what is left of the variant's cap
    for cap in (own + 1, own + extra - 1):
        summary = explore_with_levers(graph, _spec(LEVERS).model_copy(update={"max_cases_per_variant": cap}),
                                      config=config, dvfs_tables={})
        design = summary["design_axes"]
        assert svc._cases_used(summary) <= cap and summary["counts"]["cases"] == own
        assert len(design["results"]) < 5
        stopped = [e["error"] for e in design["errors"]] + design["notes"]
        assert any("exceeds" in text or "case budget exhausted" in text for text in stopped)


def test_the_pool_worker_builds_its_own_plan(graph, explored):
    # the worker receives the variant graph and the spec only: the changed graphs are never pickled
    summary = svc._explore_worker(graph, _spec(LEVERS), SimulationRunConfig(), {})
    assert canonical_json(summary["design_axes"]) == canonical_json(explored["design_axes"])
    assert "design_axes" not in svc._explore_worker(graph, _spec(), SimulationRunConfig(), {})


def test_requests_carry_lever_axes_in_either_form_and_recompute_leaves_them_out():
    by_spec = ArchExplorationRunRequest.model_validate({"scenario_ids": ["uc-a"], "spec": {"axes": {"levers": LEVERS}}})
    by_space = ArchExplorationRunRequest.model_validate({"scenario_ids": ["uc-a"], "design_space": {
        "axes": [{"lever": "sw_statistic", "values": ["mean", "max"]}, {"lever": "sw_growth", "values": [1.0, 1.1, 1.2]},
                 {"lever": "dvfs_headroom", "values": [0, 1]},
                 {"lever": "buffer_compression", "values": ["lossless", "lossy"]},
                 {"lever": "power_options", "values": ["knob", "ip_mode"]}, *LEVERS]}})
    assert by_space.spec.model_dump(mode="json") == by_spec.spec.model_dump(mode="json")
    stored = by_spec.spec.model_dump(mode="json") | {"scenario_ids": ["uc-a"], "config_profile_ref": None}
    assert stored["axes"]["levers"][0]["lever"] == "fps"
    again = variant_spec(stored)
    assert "levers" not in again["axes"] and "lever_max_sets" not in again["axes"] and "scenario_ids" not in again
    assert again["axes"]["statistics"] == stored["axes"]["statistics"]
    assert "levers" in stored["axes"]  # the stored run spec is not modified


def test_a_lossy_pick_of_the_combination_shows_as_an_iq_trade(graph, explored):
    row = next(r for r in explored["design_axes"]["results"] if r["key"] == "fps=24")
    # the fps lever itself keeps IQ, but the power shown is with lossy compression selected
    assert row["lever_iq"] == "neutral" and row["lossy"] is True and row["iq"] == "trade"
    spec = _spec(LEVERS).model_copy(update={"constraints": _spec().constraints.model_copy(update={"allow_lossy": False})})
    kept = explore_with_levers(graph, spec, config=SimulationRunConfig(), dvfs_tables={})["design_axes"]["results"]
    assert all(r["lossy"] is False and r["iq"] == r["lever_iq"] for r in kept)


def test_crop_position_and_port_tell_two_size_changes_apart(graph):
    axis = LeverAxis.model_validate({"lever": "chain_size", "params": {"node_id": "byrp"}, "values": [
        {"width": 1920, "height": 1080, "operation": "crop", "x": 0, "y": 0},
        {"width": 1920, "height": 1080, "operation": "crop", "x": 16, "y": 0},
        {"width": 1920, "height": 1080, "operation": "scale", "port": "out_main"},
        [1920, 1080]]})
    validate_levers([axis])  # four different changes of the same size
    plan = build_design_plan(graph, SimulationRunConfig(), [axis])
    assert [s["key"] for s in plan["sets"]] == [
        "chain_size[byrp]:crop=1920x1080@(0,0)", "chain_size[byrp]:crop=1920x1080@(16,0)",
        "chain_size[byrp]:scale=1920x1080@port:out_main", "chain_size[byrp]=1920x1080"]
    assert plan["dimensions"][0]["values"] == ["crop 1920x1080 @(0,0)", "crop 1920x1080 @(16,0)",
                                               "scale 1920x1080 port out_main", "1920x1080"]
    assert len({s["items"][0]["label"] for s in plan["sets"]}) == 4
    same = LeverAxis.model_validate({"lever": "chain_size", "params": {"node_id": "byrp"}, "values": [
        {"width": 1920, "height": 1080, "operation": "crop", "x": 16}, {"width": 1920, "height": 1080, "operation": "crop", "x": 16, "y": 0}]})
    with pytest.raises(ValueError, match="values must be distinct"):
        validate_levers([same])


BINDING = {"catalog_ref": "sensor-cat", "catalog_sha256": "a" * 64, "mode_label": "mode", "lineup_ref": "lineup",
           "lineup_sha256": "b" * 64, "board_config": "board", "slot": "rear"}


def test_the_plan_hands_the_catalog_preparation_to_every_changed_copy(monkeypatch, graph):
    from scenario_db.api.services import design_axes

    pinned = SimulationRunConfig.model_validate({"sensor_modes": {"sensor_rear": BINDING}})
    assert design_axes.needs_catalog(pinned) and not design_axes.needs_catalog(SimulationRunConfig())
    seen = []

    def apply(base, changes, config, domains, notes, *, prepare_sensor=None, targets=None):
        seen.append(prepare_sensor)
        if prepare_sensor is None:
            raise ValueError("pinned sensor binding requires authoritative catalog preparation")
        return prepare_sensor(base, config), config, changes
    monkeypatch.setattr(design_axes, "whatif_targets", lambda *a: {})
    monkeypatch.setattr(design_axes, "apply_whatif_changes", apply)
    levers = [LeverAxis(lever="fps", values=[24, 60])]
    alone = design_axes.build_design_plan(graph, pinned, levers)
    assert all("authoritative catalog preparation" in s["error"] for s in alone["sets"])

    def prepare(candidate, config):
        return candidate
    prepared = design_axes.build_design_plan(graph, pinned, levers, prepare_sensor=prepare)
    assert seen[-2:] == [prepare, prepare] and all("error" not in s and s["graph"] is graph for s in prepared["sets"])


def test_a_pinned_variant_is_explored_in_process_with_the_runs_session(monkeypatch, graph):
    db, calls = MagicMock(), {"released": 0}
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load",
                        lambda selection, db: analysis_inputs.AnalysisInputs(graph, {}, "dvfs-test"))
    monkeypatch.setattr(whatif_sensors, "prepare_sensor_graph", lambda session, candidate, config: ("prepared", session))
    monkeypatch.setattr(svc, "release_read_connection", lambda session: calls.__setitem__("released", calls["released"] + 1))
    scenario = SimpleNamespace(id="uc-cam-recording-e2600", project_ref="proj-a")
    request = ArchExplorationRunRequest.model_validate({
        "scenario_ids": [scenario.id], "config": {"sensor_modes": {"sensor_rear": BINDING}},
        "spec": {"axes": NARROW | {"levers": [{"lever": "fps", "values": [24]}]}, "verify": False}})
    item = svc._load_variant(db, request, scenario, VARIANT, {}, release=True)
    # a changed copy is re-validated through the run's own session, which is given back afterwards
    assert item["prepare_sensor"]("candidate", item["config"]) == ("prepared", db) and calls["released"] == 1
    kept = svc._load_variant(db, request, scenario, VARIANT, {})  # registration callers keep their transaction
    assert kept["prepare_sensor"]("candidate", kept["config"]) == ("prepared", db) and calls["released"] == 1

    seen = {}

    def explore(base, spec, **kw):
        seen.update(kw)
        return {"counts": {"cases": 1}}
    monkeypatch.setattr(svc, "explore_with_levers", explore)
    svc._explore_item(item, 100)
    assert seen["prepare_sensor"] is item["prepare_sensor"]
    # the closure holds the session: such a variant is never sent to a pool worker
    assert svc._explore_parallel([item, item, item, item], 100, lambda variant_id: None) == {}
    # without a pinned binding, or without lever axes, nothing needs the session
    plain = request.model_copy(update={"config": SimulationRunConfig()})
    assert svc._load_variant(db, plain, scenario, VARIANT, {})["prepare_sensor"] is None
    no_levers = request.model_copy(update={"spec": _spec()})
    assert svc._load_variant(db, no_levers, scenario, VARIANT, {})["prepare_sensor"] is None


# ------------------------------------------------------------------- screening
WIDE = [
    {"lever": "fps", "values": [24, 60]},
    {"lever": "llc_alloc", "params": {"buffer_id": "PYRAMID_L0"}, "values": ["off"]},
    {"lever": "history_interval", "params": {"buffer_id": "TNR_PREV_L0"}, "values": [2]},
    {"lever": "power_knob", "params": {"param": "pyramid_l0"}, "values": ["skip"]},
]  # 3 x 2 x 2 x 2 - 1 = 23 combinations, 5 single values


def _screen(levers, cap):
    return _spec(levers, lever_search="screen", lever_max_sets=cap)


@pytest.fixture(scope="module")
def screened(graph):
    return explore_with_levers(graph, _screen(WIDE, 9), config=SimulationRunConfig(), dvfs_tables={})["design_axes"]


def test_screening_tries_every_value_alone_then_combines_the_top_levers(graph, screened):
    search = screened["search"]
    assert search["mode"] == "screened" and search["full_factorial"] == 23 and search["one_at_a_time"] == 5
    ranking = search["ranking"]
    # ordered by the largest power change one value of the lever made on its own
    impacts = [r["impact_mw"] for r in ranking]
    assert impacts == sorted(impacts, reverse=True) and ranking[0]["lever"] == "fps"
    alone = {r["key"]: r for r in screened["results"] if " | " not in r["key"]}
    assert len(alone) == 5
    assert ranking[0]["impact_mw"] == pytest.approx(max(abs(alone["fps=24"]["raw_delta_mw"]), abs(alone["fps=60"]["raw_delta_mw"])))
    # 9 - 5 = 4 combinations left: the top two levers give 2, a third lever would need 7
    assert [r["combined"] for r in ranking] == [True, True, False, False] and search["combined"] == 2
    second = ranking[1]["lever"]
    combined = [r["key"] for r in screened["results"] if " | " in r["key"]]
    assert len(combined) == 2 and all(k.startswith("fps=") and second in k for k in combined)
    assert screened["sets"] == 7 and len(screened["results"]) == 7 and not screened["errors"]


def test_a_screened_row_is_the_same_row_the_exhaustive_search_gives(graph, screened):
    full = explore_with_levers(graph, _spec(WIDE), config=SimulationRunConfig(), dvfs_tables={})["design_axes"]
    assert full["search"] == {"mode": "exhaustive", "full_factorial": 23, "one_at_a_time": 5, "combined": 18}
    assert full["sets"] == 23
    by_key = {r["key"]: r for r in full["results"]}
    assert all(canonical_json(by_key[r["key"]]) == canonical_json(r) for r in screened["results"])


def test_screening_a_space_that_fits_is_the_exhaustive_search(graph, explored):
    fits = explore_with_levers(graph, _screen(LEVERS, 64), config=SimulationRunConfig(), dvfs_tables={})["design_axes"]
    assert fits["search"]["mode"] == "exhaustive" and "ranking" not in fits["search"]
    assert canonical_json(fits) == canonical_json(explored["design_axes"])


def test_a_value_that_fails_alone_is_ranked_last_and_not_combined(graph):
    levers = [*WIDE[:2], {"lever": "chain_size", "params": {"node_id": "no_such_node"}, "values": [[1920, 1080], [1280, 720]]},
              WIDE[2]]  # 3 x 2 x 3 x 2 - 1 = 35
    design = explore_with_levers(graph, _screen(levers, 9), config=SimulationRunConfig(), dvfs_tables={})["design_axes"]
    ranking = design["search"]["ranking"]
    assert ranking[-1] == {"lever": "chain_size", "label": "IP crop · downscale · no_such_node", "impact_mw": None,
                           "impact_pct": None, "combined": False}
    assert len(design["errors"]) == 2 and all("no_such_node" in e["key"] and " | " not in e["key"] for e in design["errors"])
    assert all("no_such_node" not in r["key"] for r in design["results"])


def test_nothing_is_combined_when_the_cap_only_holds_the_single_values(graph):
    design = explore_with_levers(graph, _screen(WIDE, 5), config=SimulationRunConfig(), dvfs_tables={})["design_axes"]
    assert design["sets"] == 5 and design["search"]["combined"] == 0
    assert [r["combined"] for r in design["search"]["ranking"]] == [False] * 4
    assert all(r["impact_mw"] is not None for r in design["search"]["ranking"])


def test_a_case_budget_that_ends_during_the_single_values_leaves_the_levers_unranked(graph):
    own = explore_variant(graph, _spec(), config=SimulationRunConfig())["counts"]["cases"]
    spec = _screen(WIDE, 9).model_copy(update={"max_cases_per_variant": own + 1})
    design = explore_with_levers(graph, spec, config=SimulationRunConfig(), dvfs_tables={})["design_axes"]
    search = design["search"]
    assert search["mode"] == "screened" and search["combined"] == 0
    assert all(r["impact_mw"] is None and not r["combined"] for r in search["ranking"])
    assert design["sets"] == 5


def test_the_search_mode_does_not_change_the_variant_or_its_hash(graph):
    config = SimulationRunConfig()
    assert input_hash(graph, _screen(WIDE, 9), config, {}) == input_hash(graph, _spec(), config, {})
    assert variant_spec(_screen(WIDE, 9).model_dump(mode="json"))["axes"].keys() == _spec().model_dump(mode="json")["axes"].keys()
