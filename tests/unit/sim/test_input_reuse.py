"""DMA-only adapter path and compression-candidate reuse give the same results as the full path."""

from __future__ import annotations

import itertools
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import arch_exploration as ax  # noqa: E402
from scenario_db.sim import power_options as po  # noqa: E402
from scenario_db.sim.adapter import build_port_transfers, build_simulation_inputs  # noqa: E402
from scenario_db.sim.models import DVFSTable, SimulationRunConfig  # noqa: E402

UHD30 = "cam-rec-r1-uhd30-vdis"
CASES = [
    ("uc-cam-recording-e2600", UHD30),
    ("uc-cam-recording-e2600", "cam-rec-r1-fhd30-sdr"),
    ("uc-cam-recording-e2600", "cam-rec-r1-fhd60-supersteady"),
    ("uc-cam-recording-apv-e2600", "cam-rec-apv-uhd60-422-sdr"),
    ("uc-cam-preview-e2600", "cam-prev-r1-30"),
    ("uc-cam-capture-e2600", "cam-cap-r1-sf"),
]


@pytest.fixture(scope="module")
def graph_of():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    raws: dict[str, object] = {}

    def make(scenario: str, variant: str):
        if scenario not in raws:
            raws[scenario] = read(FIXTURE / "02_definition" / f"{scenario}.yaml")
        return graph_from_fixture(raws[scenario], variant, catalog)
    return make


@pytest.fixture(scope="module")
def tables():
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


def _same_as_full(graph, config=None):
    fps, workloads, transfers = build_port_transfers(graph, config)
    full = build_simulation_inputs(graph, config)
    assert fps == full.config.fps
    assert [(w.node_id, w.fps) for w in workloads] == [(w.node_id, w.fps) for w in full.workloads]
    assert [t.model_dump() for t in transfers] == [t.model_dump() for t in full.port_transfers]


@pytest.mark.parametrize(("scenario", "variant"), CASES)
def test_port_transfers_match_the_full_adapter(graph_of, scenario, variant):
    _same_as_full(graph_of(scenario, variant))


def test_port_transfers_match_with_buffer_override_inactive_node_and_fps(graph_of):
    graph = graph_of("uc-cam-recording-e2600", UHD30)
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    bid = sorted(buffers)[0]
    _same_as_full(ax._with_buffer(graph, bid, {"compression": "COMP_YUV_LOSSY", "comp_ratio": 0.5}))
    variant = deepcopy(graph.variant)
    node = next(str(n["id"]) for n in graph.pipeline_nodes if "mtnr" in str(n["id"]).lower())
    variant.node_configs = {**(variant.node_configs or {}), node: {**((variant.node_configs or {}).get(node) or {}),
                                                                  "sim": {"active": False}}}
    _same_as_full(replace(graph, variant=variant))
    _same_as_full(graph, SimulationRunConfig(fps=60))


def test_with_buffer_copies_only_the_overrides(graph_of):
    graph = graph_of("uc-cam-recording-e2600", UHD30)
    before = deepcopy(graph.variant.buffer_overrides)
    patched = ax._with_buffer(graph, "some_buffer", {"compression": "COMP_OFF"})
    assert graph.variant.buffer_overrides == before
    assert patched.variant.buffer_overrides["some_buffer"] == {"compression": "COMP_OFF"}
    assert patched.variant.node_configs is graph.variant.node_configs


def _option_graphs(graph):
    dims, _ = po.option_dimensions(graph)
    return {po.set_key(items): (items, po.apply_option_set(graph, items)) for items in po.option_sets(dims)}


def test_compression_key_follows_the_dma_inputs(graph_of):
    graph = graph_of("uc-cam-recording-e2600", UHD30)
    config, spec = SimulationRunConfig(), ax.ArchExplorationSpec()
    axis, sw = ax._comp_axis(spec), {"sw_a"}
    base = ax.compression_key(graph, config, axis, sw)
    assert base == ax.compression_key(graph, config, axis, set(sw))
    assert base != ax.compression_key(graph, config, axis, {"sw_b"})
    assert base != ax.compression_key(graph, config.model_copy(update={"fps": 60}), axis, sw)
    assert base != ax.compression_key(graph, config, axis.model_copy(update={"max_buffers": 1}), sw)
    bid = sorted((graph.scenario.pipeline or {}).get("buffers") or {})[0]
    assert base != ax.compression_key(ax._with_buffer(graph, bid, {"comp_ratio": 0.7}), config, axis, sw)
    sets = _option_graphs(graph)
    mode_only = [g for items, g in sets.values() if all(i["kind"] == "ip_mode" for i in items)]
    knob = [g for items, g in sets.values() if any(i["kind"] == "knob" for i in items)]
    assert mode_only and knob
    # an IP-mode swap leaves the DMA inputs alone; a knob (crop / pyramid) changes them
    assert all(ax.compression_key(g, config, axis, sw) == base for g in mode_only)
    assert all(ax.compression_key(g, config, axis, sw) != base for g in knob)


def test_power_option_reuse_is_result_identical(graph_of, tables, monkeypatch):
    graph = graph_of("uc-cam-recording-e2600", UHD30)
    calls = []
    real = ax.compression_candidates

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(ax, "compression_candidates", counted)
    reused = ax.explore_variant(graph, dvfs_tables=tables)
    with_reuse = len(calls)
    counter = itertools.count()
    monkeypatch.setattr(ax, "compression_key", lambda *a, **k: f"never-{next(counter)}")
    calls.clear()
    fresh = ax.explore_variant(graph, dvfs_tables=tables)
    sets = _option_graphs(graph)
    n_mode_only = sum(all(i["kind"] == "ip_mode" for i in items) for items, _ in sets.values())
    assert len(calls) == 1 + len(sets)
    assert with_reuse == len(calls) - n_mode_only
    assert reused == fresh
