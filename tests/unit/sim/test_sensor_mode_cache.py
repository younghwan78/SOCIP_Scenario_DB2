"""Sensor selection reuse is local to adaptation and follows mutable overrides."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import adapter, external_devices as devices  # noqa: E402
from scenario_db.sim.sensor_timing import calculate_sensor_timing  # noqa: E402


MODE_FIELDS = ("mode", "selected_mode", "sensor_mode", "sensor_mode_ref")


@pytest.fixture(scope="module")
def graph_factory():
    catalog = {}
    for path in sorted((FIXTURE / "00_hw").glob("ip-*.yaml")):
        doc = read(path)
        catalog[doc["id"]] = IpCatalog(
            id=doc["id"], schema_version=doc["schema_version"], category=doc["category"],
            hierarchy=doc["hierarchy"], capabilities=doc["capabilities"], yaml_sha256="fixture",
        )
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    return lambda: graph_from_fixture(raw, "cam-rec-r1-uhd30-vdis", catalog)


def sensor(graph):
    return next(node for node in graph.pipeline_nodes if node["id"] == "sensor_rear")


def mode_ids(graph, node):
    modes = graph.ip_catalog[node["ip_ref"]].capabilities["properties"]["modes"]
    return [key for key, mode in modes.items() if isinstance(mode, dict)][:2]


def clear_selection(graph, node):
    cfg = graph.variant.node_configs[node["id"]]
    for key in (*MODE_FIELDS, "resolved_sensor_mode", "sensor_readout"):
        cfg.pop(key, None)
    for key in ("sensor_mode", "sensor_mode_ref", "sensor"):
        graph.variant.design_conditions.pop(key, None)
    return cfg


def test_repeated_node_resolution_is_cached_inside_each_adapter_call(graph_factory, monkeypatch):
    graph = graph_factory()
    calls = []
    original_base = devices._base_selected_sensor_mode
    original_shapes = adapter.propagate_shapes

    def counted_base(candidate, node=None):
        calls.append(node.get("id") if node else None)
        return original_base(candidate, node)

    def probe(candidate):
        node = sensor(candidate)
        before = calls.count(node["id"])
        first = devices.selected_sensor_mode(candidate, node)
        second = devices.selected_sensor_mode(candidate, node)
        assert first == second
        assert first is not second
        assert calls.count(node["id"]) == before + 1
        return original_shapes(candidate)

    monkeypatch.setattr(devices, "_base_selected_sensor_mode", counted_base)
    monkeypatch.setattr(adapter, "propagate_shapes", probe)
    first = adapter.build_simulation_inputs(graph)
    assert calls.count("sensor_rear") == 1
    assert devices._SENSOR_MODE_CACHE.get() is None
    second = adapter.build_simulation_inputs(graph)
    assert calls.count("sensor_rear") == 2
    assert first.model_dump() == second.model_dump()


def test_fallback_nodes_share_base_resolution(graph_factory, monkeypatch):
    graph = graph_factory()
    calls = []
    original = devices._preferred_sensor_mode

    def counted(modes, candidate):
        calls.append(candidate)
        return original(modes, candidate)

    monkeypatch.setattr(devices, "_preferred_sensor_mode", counted)
    with devices.sensor_mode_cache():
        first = devices.selected_sensor_mode(graph, {"id": "fallback-a"})
        second = devices.selected_sensor_mode(graph, {"id": "fallback-b"})
    assert first == second
    assert len(calls) == 1


@pytest.mark.parametrize("field", MODE_FIELDS)
def test_selected_mode_mutation_misses_cache(graph_factory, field):
    graph = graph_factory()
    node = sensor(graph)
    cfg = clear_selection(graph, node)
    first_id, second_id = mode_ids(graph, node)
    with devices.sensor_mode_cache():
        cfg[field] = first_id
        assert devices.selected_sensor_mode(graph, node)["mode_id"] == first_id
        cfg[field] = second_id
        assert devices.selected_sensor_mode(graph, node)["mode_id"] == second_id


@pytest.mark.parametrize("field", ("sensor_mode", "sensor_mode_ref", "sensor"))
def test_design_mode_mutation_misses_cache(graph_factory, field):
    graph = graph_factory()
    node = sensor(graph)
    clear_selection(graph, node)
    first_id, second_id = mode_ids(graph, node)
    with devices.sensor_mode_cache():
        graph.variant.design_conditions[field] = first_id
        assert devices.selected_sensor_mode(graph, node)["mode_id"] == first_id
        graph.variant.design_conditions[field] = second_id
        assert devices.selected_sensor_mode(graph, node)["mode_id"] == second_id


def test_readout_mutation_misses_cache(graph_factory):
    graph = graph_factory()
    node = sensor(graph)
    width, height = devices.selected_sensor_mode(graph, node)["sensor_size"]
    timing = {
        "active_width": width, "active_height": height, "pixel_clock_hz": 1_000_000_000,
        "line_length_pck": 5000, "frame_length_lines": 4000,
        "source": {"basis": "test timing"},
    }
    cfg = graph.variant.node_configs[node["id"]]
    with devices.sensor_mode_cache():
        original = devices.selected_sensor_mode(graph, node)
        cfg["sensor_readout"] = timing
        first = devices.selected_sensor_mode(graph, node)
        assert first["v_valid_ms"] == calculate_sensor_timing(timing)["valid_time_ms"]
        timing["pixel_clock_hz"] *= 2
        second = devices.selected_sensor_mode(graph, node)
        assert second["v_valid_ms"] == first["v_valid_ms"] / 2
        assert second["sensor_fps"] == first["sensor_fps"] * 2
        del cfg["sensor_readout"]
        assert devices.selected_sensor_mode(graph, node) == original


def test_resolved_mode_nested_mutation_and_replacement_miss_cache(graph_factory):
    graph = graph_factory()
    node = sensor(graph)
    cfg = graph.variant.node_configs[node["id"]]
    initial = devices.selected_sensor_mode(graph, node)
    payload = deepcopy(initial)
    with devices.sensor_mode_cache():
        cfg["resolved_sensor_mode"] = payload
        assert devices.selected_sensor_mode(graph, node) == initial
        payload["sensor_size"][0] += 2
        assert devices.selected_sensor_mode(graph, node)["sensor_size"][0] == initial["sensor_size"][0] + 2
        cfg["resolved_sensor_mode"] = deepcopy(initial)
        payload["sensor_size"][0] += 2
        assert devices.selected_sensor_mode(graph, node) == initial


@pytest.mark.parametrize("resolved", (False, True))
@pytest.mark.parametrize("cached", (False, True))
def test_caller_mutation_does_not_change_later_results(graph_factory, resolved, cached):
    graph = graph_factory()
    node = sensor(graph)
    expected = devices.selected_sensor_mode(graph, node)
    if resolved:
        expected["transport"] = {"vc_rows": [{"bits_per_pixel": 10}]}
        graph.variant.node_configs[node["id"]]["resolved_sensor_mode"] = deepcopy(expected)
    with devices.sensor_mode_cache() if cached else nullcontext():
        first = devices.selected_sensor_mode(graph, node)
        first["mode_id"] = "caller-mutated"
        first["sensor_size"][0] = 1
        first["active_size"][0] = 2
        if resolved:
            first["transport"]["vc_rows"][0]["bits_per_pixel"] = 99
        assert devices.selected_sensor_mode(graph, node) == expected


def test_graph_identity_and_node_ip_ref_are_distinct(graph_factory):
    first_graph, second_graph = graph_factory(), graph_factory()
    first_node, second_node = sensor(first_graph), sensor(second_graph)
    first_cfg = clear_selection(first_graph, first_node)
    second_cfg = clear_selection(second_graph, second_node)
    first_id, second_id = mode_ids(first_graph, first_node)
    first_cfg["mode"], second_cfg["mode"] = first_id, second_id
    with devices.sensor_mode_cache():
        assert devices.selected_sensor_mode(first_graph, first_node)["mode_id"] == first_id
        assert devices.selected_sensor_mode(second_graph, second_node)["mode_id"] == second_id
        replacement = {**first_node, "ip_ref": next(
            ref for ref, row in first_graph.ip_catalog.items()
            if row.category == "sensor" and ref != first_node["ip_ref"]
        )}
        assert devices.selected_sensor_mode(first_graph, replacement)["ip_ref"] == replacement["ip_ref"]


@pytest.mark.parametrize("field,value", (
    ("fps", 60), ("resolution", "8K"), ("size", "4000x3000"),
    ("sensor_place", "front"), ("sensor_places", ["front"]),
    ("custom_condition", "video"),
))
def test_design_changes_match_uncached_resolution(graph_factory, field, value):
    graph = graph_factory()
    node = sensor(graph)
    clear_selection(graph, node)
    with devices.sensor_mode_cache():
        devices.selected_sensor_mode(graph)
        graph.variant.design_conditions[field] = value
        actual = devices.selected_sensor_mode(graph)
    assert actual == devices.selected_sensor_mode(graph)


def test_adapter_failure_restores_outer_context(graph_factory, monkeypatch):
    def fail(_graph):
        raise RuntimeError("adapter probe")

    monkeypatch.setattr(adapter, "propagate_shapes", fail)
    with devices.sensor_mode_cache():
        outer = devices._SENSOR_MODE_CACHE.get()
        with pytest.raises(RuntimeError, match="adapter probe"):
            adapter.build_simulation_inputs(graph_factory())
        assert devices._SENSOR_MODE_CACHE.get() is outer
    assert devices._SENSOR_MODE_CACHE.get() is None


def test_catalog_sizes_are_parsed_once_for_repeated_values():
    devices._string_size_tuple.cache_clear()
    devices._size_from_values.cache_clear()
    for _ in range(3):
        assert devices._size_tuple("4080x2296") == (4080, 2296)
        assert devices._size_tuple([4080, 2296]) == (4080, 2296)
        assert devices._size_tuple((4080, 2296)) == (4080, 2296)
    assert devices._string_size_tuple.cache_info().misses == 1
    assert devices._size_from_values.cache_info().misses == 2  # string and integer dimensions


@pytest.mark.parametrize("value,expected", (
    ("10X20", (10, 20)), ("invalidx20", None), ("1020", None),
    ([None, "20"], (0, 20)), ([10], None), ([[10], 20], None),
))
def test_size_cache_preserves_parsing_behavior(value, expected):
    assert devices._size_tuple(value) == expected
