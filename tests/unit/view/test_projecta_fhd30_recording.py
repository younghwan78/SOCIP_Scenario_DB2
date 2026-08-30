"""Legacy-parity validation for the demo projectA FHD30 recording scenario."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view import service

pytestmark = pytest.mark.unit

FIXTURE_ROOT = Path("demo/fixtures")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _ip_catalog() -> dict[str, SimpleNamespace]:
    catalog: dict[str, SimpleNamespace] = {}
    for path in (FIXTURE_ROOT / "00_hw").glob("ip-*.yaml"):
        raw = _load_yaml(path)
        catalog[str(raw["id"])] = SimpleNamespace(
            category=raw.get("category"),
            capabilities=raw.get("capabilities") or {},
            hierarchy=raw.get("hierarchy") or {},
        )
    return catalog


def _graph(variant_id: str) -> CanonicalScenarioGraph:
    raw = _load_yaml(FIXTURE_ROOT / "02_definition" / "uc-projecta-fhd30-recording.yaml")
    variant = next(item for item in raw["variants"] if item["id"] == variant_id)
    scenario = SimpleNamespace(
        id=raw["id"],
        project_ref=raw["project_ref"],
        metadata_=raw.get("metadata") or {},
        pipeline=raw.get("pipeline") or {},
        size_profile=raw.get("size_profile") or {},
    )
    resolved_variant = SimpleNamespace(
        id=variant["id"],
        severity=variant.get("severity"),
        design_conditions=variant.get("design_conditions") or {},
        size_overrides=variant.get("size_overrides") or {},
        routing_switch=variant.get("routing_switch") or {},
        topology_patch=variant.get("topology_patch") or {},
        node_configs=variant.get("node_configs") or {},
        buffer_overrides=variant.get("buffer_overrides") or {},
        ip_requirements=variant.get("ip_requirements") or {},
        sw_requirements=variant.get("sw_requirements") or {},
        resolved=True,
        inheritance_chain=[variant["id"]],
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=resolved_variant,
        soc=SimpleNamespace(id="soc-exynos2500"),
        ip_catalog=_ip_catalog(),
    )


def _level1_view():
    return service._project_semantic_level1(_graph("FHD30-recording"))


def test_fhd30_chain_matches_legacy_dma_port_pairs():
    view = _level1_view()
    by_buffer = {edge.data.buffer_ref: edge.data for edge in view.edges if edge.data.buffer_ref}

    raw = by_buffer["RAW_BAYER_MAIN"]
    assert [(p.src, p.dst) for p in raw.port_pairs] == [("CSIS_WDMA", "COMP_RD0_RDMA")]
    assert (raw.memory.width, raw.memory.height) == (4000, 2252)
    assert raw.memory.format == "BAYER_PACKED"
    assert raw.memory.bitdepth == 12

    record = by_buffer["RECORD_BUF"]
    assert record.port_pairs[0].src == "P0_WDMA"
    assert (record.memory.width, record.memory.height) == (1920, 1080)


def test_fhd30_mlsc_pyramid_buffers_reach_mtnr_with_declared_sizes():
    view = _level1_view()
    pyramid = {
        edge.data.buffer_ref: edge.data
        for edge in view.edges
        if edge.data.buffer_ref and edge.data.buffer_ref.startswith("MLSC_")
    }
    expected = {
        "MLSC_L0_BUF": (1920, 1080),
        "MLSC_L1_BUF": (960, 540),
        "MLSC_L2_BUF": (480, 270),
        "MLSC_L3_BUF": (240, 135),
        "MLSC_G4_BUF": (120, 68),
    }
    for name, (width, height) in expected.items():
        assert name in pyramid, name
        memory = pyramid[name].memory
        assert (memory.width, memory.height) == (width, height), name

    mtnr1_dsts = {
        pair.dst
        for edge in view.edges
        for pair in edge.data.port_pairs or []
        if edge.data.target.endswith("mtnr1")
    }
    assert {"L1_RDMA", "L2_RDMA", "L3_RDMA", "G4_RDMA"} <= mtnr1_dsts


def test_fhd30_otf_chain_declares_fifo_pairs():
    view = _level1_view()
    otf_pairs = {
        (edge.data.source, edge.data.target): [(p.src, p.dst) for p in edge.data.port_pairs or []]
        for edge in view.edges
        if not edge.data.buffer_ref and edge.data.port_pairs
    }
    by_target_suffix = {
        (src.split("ip-")[-1], dst.split("ip-")[-1]): pairs for (src, dst), pairs in otf_pairs.items()
    }
    assert by_target_suffix[("csis-link", "csis")] == [("LINK", "NFI_DEC")]
    assert by_target_suffix[("csis", "pdp")] == [("IBUF", "REORDER")]
    assert by_target_suffix[("mtnr0", "msnr")] == [("L0_COUTFIFO", "L0_CINFIFO")]
    assert len(by_target_suffix[("mtnr1", "msnr")]) == 4
