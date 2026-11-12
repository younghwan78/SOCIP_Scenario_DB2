"""Design space <-> exploration spec: the conversion is lossless and the absent-axis rule is explicit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scenario_db.sim.arch_exploration import ArchExplorationSpec, explore_variant, input_hash
from scenario_db.sim.design_space import (
    BUILTIN_LEVERS,
    DesignSpace,
    LeverAxis,
    builtin_catalog,
    design_space_from_spec,
    design_space_of_stored_spec,
    resim_axes,
    spec_from_design_space,
)
from scenario_db.sim.models import SimulationRunConfig

SPECS = {
    "default": {},
    "narrow": {"axes": {"statistics": ["mean"], "runtime_scales": [1.0], "dvfs_headroom_levels": 0},
               "objective": {"statistic": "mean"}},
    "wide": {"axes": {"statistics": ["min", "mean", "max"], "runtime_scales": [0.9, 1.0, 1.3, 1.5], "eis": "on",
                      "dvfs_headroom_levels": 3},
             "objective": {"statistic": "max", "runtime_scale": 1.3, "tie_pct": 2.5}, "top_n": 7},
    "compression_params": {"axes": {"compression": {
        "modes": ["lossless"], "ratio_overrides": {"COMP_YUV_LOSSLESS": 0.6}, "buffers": ["b1", "b2"],
        "include_unsupported": True, "require_declared": False, "max_buffers": 3, "min_saving_mbs": 0.0}}},
    "compression_off_with_params": {"axes": {"compression": {"enabled": False, "modes": ["lossless"], "max_buffers": 2}}},
    "options_off": {"axes": {"power_options": {"enabled": False, "include_knobs": False, "max_sets": 8}}},
    "options_modes_only": {"axes": {"power_options": {"include_knobs": False, "max_sets": 256}}},
    "options_none": {"axes": {"power_options": {"include_knobs": False, "include_modes": False}}},
    "constraints": {"constraints": {"power_budget_mw": 900.0, "bw_budget_mbs": 4000.0, "allow_lossy": False,
                                    "peak_bw_limit_mbs": 5000.0, "llc_capacity_mb": 12.0},
                    "verify": False, "verify_tolerance_pct": 1.0, "max_cases_per_variant": 1000},
    "timing": {"timing": {"statistic": "mean", "frames": 16, "throughput_model": "pipelined"}},
}


@pytest.mark.parametrize("name", SPECS)
def test_round_trip_is_lossless(name):
    spec = ArchExplorationSpec.model_validate(SPECS[name])
    space = design_space_from_spec(spec)
    back = spec_from_design_space(space)
    assert back.model_dump(mode="json") == spec.model_dump(mode="json")
    assert back.timing.model_fields_set == spec.timing.model_fields_set  # policy defaults still apply
    # ... and through JSON, the form a client posts
    posted = DesignSpace.model_validate(json.loads(json.dumps(space.model_dump(mode="json"))))
    assert spec_from_design_space(posted).model_dump(mode="json") == spec.model_dump(mode="json")
    assert [a.lever for a in space.axes] == list(BUILTIN_LEVERS)


def test_round_trip_keeps_the_input_hash_and_the_result():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from check_engine_equivalence import canonical_json
    from verify_is_v15_camera import FIXTURE, graph_from_fixture, read

    from scenario_db.db.models.capability import IpCatalog

    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    graph = graph_from_fixture(read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml"), "cam-rec-r1-fhd30-sdr", catalog)
    spec = ArchExplorationSpec.model_validate(SPECS["narrow"] | {"verify": False})
    back = spec_from_design_space(design_space_from_spec(spec))
    config = SimulationRunConfig()
    assert input_hash(graph, back, config, {}) == input_hash(graph, spec, config, {})
    assert canonical_json(explore_variant(graph, back, config=config)) == canonical_json(explore_variant(graph, spec, config=config))


def test_a_lever_left_out_is_held_at_its_neutral_value():
    spec = spec_from_design_space(DesignSpace.model_validate({
        "axes": [{"lever": "sw_growth", "values": [1.0, 1.2]}],
        "objective": {"statistic": "mean", "runtime_scale": 1.2}}))
    axes = spec.axes
    assert axes.statistics == ["mean"] and axes.runtime_scales == [1.0, 1.2] and axes.eis == "auto"
    assert axes.dvfs_headroom_levels == 0
    assert axes.compression.enabled is False and axes.power_options.enabled is False
    empty = spec_from_design_space(DesignSpace()).axes
    assert empty.statistics == ["max"] and empty.runtime_scales == [1.0]


def test_listed_levers_use_the_engine_defaults_for_their_params():
    spec = spec_from_design_space(DesignSpace(axes=[
        LeverAxis(lever="buffer_compression", values=["lossless"]),
        LeverAxis(lever="power_options", values=["ip_mode"]),
        LeverAxis(lever="dvfs_headroom", values=[0, 1, 2])]))
    assert spec.axes.compression.enabled and spec.axes.compression.modes == ["lossless"]
    assert spec.axes.compression.max_buffers == 8
    assert spec.axes.power_options.include_modes and not spec.axes.power_options.include_knobs
    assert spec.axes.dvfs_headroom_levels == 2


@pytest.mark.parametrize("axis, message", [
    ({"lever": "dvfs_headroom", "values": [1, 2]}, "raise steps 0..k"),
    ({"lever": "dvfs_headroom", "values": []}, "raise steps 0..k"),
    ({"lever": "dvfs_headroom", "values": [0, True]}, "raise steps 0..k"),
    ({"lever": "dvfs_headroom", "values": [0, 1, 2, 3, 4]}, "dvfs_headroom_levels"),
    ({"lever": "eis", "values": ["on", "off"]}, "exactly one value"),
    ({"lever": "eis", "values": ["sometimes"]}, "eis"),
    ({"lever": "sw_statistic", "values": ["p99"]}, "statistics"),
    ({"lever": "sw_statistic", "values": []}, "statistics"),
    ({"lever": "sw_growth", "values": [0]}, "runtime_scales"),
    ({"lever": "sw_growth", "values": [1.0], "params": {"step": 0.1}}, "unknown params step"),
    ({"lever": "buffer_compression", "values": ["zip"]}, "modes"),
    ({"lever": "buffer_compression", "values": ["lossy"], "params": {"max_buffers": 99}}, "max_buffers"),
    ({"lever": "buffer_compression", "values": ["lossy"], "params": {"ratio": 0.5}}, "unknown params ratio"),
    ({"lever": "power_options", "values": ["knob", "knob"]}, "distinct items"),
    ({"lever": "power_options", "values": ["sensor"]}, "distinct items"),
    ({"lever": "power_options", "values": ["knob"], "params": {"max_sets": 0}}, "max_sets"),
])
def test_invalid_axes_are_refused(axis, message):
    with pytest.raises(ValueError, match=message):
        spec_from_design_space(DesignSpace.model_validate({"axes": [axis]}))


def test_a_builtin_lever_is_listed_once():
    with pytest.raises(ValueError, match="more than once"):
        DesignSpace.model_validate({"axes": [{"lever": "eis", "values": ["on"]}, {"lever": "eis", "values": ["off"]}]})


def test_other_axes_become_the_re_simulation_levers_of_the_spec():
    space = DesignSpace.model_validate({"max_lever_sets": 8, "axes": [
        {"lever": "sw_growth", "values": [1.0]},
        {"lever": "chain_size", "params": {"node_id": "mcsc"}, "values": [{"width": 1920, "height": 1080}]},
        {"lever": "fps", "values": [24, 60], "label": "frame rate"}]})
    assert [a.lever for a in resim_axes(space)] == ["chain_size", "fps"]
    spec = spec_from_design_space(space)
    assert [a.lever for a in spec.axes.levers] == ["chain_size", "fps"] and spec.axes.lever_max_sets == 8
    assert spec.axes.runtime_scales == [1.0]
    # ... and back: built-in axes first, then the lever axes as written
    back = design_space_from_spec(spec)
    assert [a.lever for a in back.axes] == [*BUILTIN_LEVERS, "chain_size", "fps"]
    assert back.axes[-1].label == "frame rate" and back.max_lever_sets == 8
    assert spec_from_design_space(back).model_dump(mode="json") == spec.model_dump(mode="json")


def test_the_caller_says_which_levers_it_can_explore():
    space = DesignSpace.model_validate({"axes": [
        {"lever": "fps", "values": [24]}, {"lever": "compression", "params": {"buffer_id": "b"}, "values": ["COMP_OFF"]}]})
    spec_from_design_space(space)  # no check without a catalog
    with pytest.raises(ValueError, match="lever cannot be explored as an axis: compression"):
        spec_from_design_space(space, explorable=("fps",), known=("fps", "compression"))
    mixed = space.model_copy(update={"axes": [*space.axes, LeverAxis(lever="warp_drive", values=[1])]})
    with pytest.raises(ValueError, match="unknown lever: warp_drive"):
        spec_from_design_space(mixed, explorable=("fps",), known=("fps", "compression"))


def test_lever_axes_are_bounded_and_do_not_change_specs_without_them():
    from scenario_db.sim.arch_exploration import ExplorationAxes, lever_set_count

    assert "levers" not in ArchExplorationSpec().model_dump(mode="json")["axes"]
    assert "lever_max_sets" not in ExplorationAxes(lever_max_sets=10).model_dump()
    axes = ExplorationAxes(levers=[LeverAxis(lever="fps", values=[24, 60]), LeverAxis(lever="llc_alloc", values=["off"])])
    assert lever_set_count(axes.levers) == 5  # (2 + 1) x (1 + 1) - the unchanged variant
    assert axes.model_dump()["lever_max_sets"] == 64
    with pytest.raises(ValueError, match="at least one value"):
        ExplorationAxes(levers=[LeverAxis(lever="fps", values=[])])
    with pytest.raises(ValueError, match="at most 16 values"):
        ExplorationAxes(levers=[LeverAxis(lever="fps", values=list(range(1, 18)))])
    with pytest.raises(ValueError, match="5 combinations > lever_max_sets 4"):
        ExplorationAxes(levers=axes.levers, lever_max_sets=4)


def test_stored_run_specs_show_their_design_space():
    default = ArchExplorationSpec().model_dump(mode="json")
    stored = default | {"scenario_ids": ["uc-a"], "category": None, "config_profile_ref": "cfg", "manifest_available": True}
    shown = design_space_of_stored_spec(stored)
    assert shown is not None and shown["schema_version"] == "sdb.designspace/1"
    assert [a["lever"] for a in shown["axes"]] == list(BUILTIN_LEVERS)
    assert spec_from_design_space(DesignSpace.model_validate(shown)).model_dump(mode="json") == default
    # a spec written by an older engine that no longer validates is shown without one, not as an error
    assert design_space_of_stored_spec(stored | {"axes": {"statistics": ["p99"]}}) is None
    assert design_space_of_stored_spec({"axes": {"removed_axis": 1}}) is None
    assert design_space_of_stored_spec(None) is not None  # no stored spec = the default spec


def test_builtin_catalog_lists_the_six_engine_axes_with_default_values():
    rows = {row["id"]: row for row in builtin_catalog()}
    assert list(rows) == ["sw_statistic", "sw_growth", "eis", "dvfs_headroom", "buffer_compression", "power_options"]
    assert all(row["source"] == "builtin" and row["explorable"] for row in rows.values())
    assert rows["sw_growth"]["default"]["values"] == [1.0, 1.1, 1.2]
    assert rows["dvfs_headroom"]["default"]["values"] == [0, 1]
    assert rows["buffer_compression"]["default"]["params"]["max_buffers"] == 8
    assert {row["evaluation"] for row in rows.values()} == {"timeline", "analytic", "resim"}
