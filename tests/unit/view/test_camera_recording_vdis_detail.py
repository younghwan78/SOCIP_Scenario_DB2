"""IS v15 validation for the cam-rec-r1-fhd30-vdis projection."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_view_projection_golden as golden  # noqa: E402

pytestmark = pytest.mark.unit

GRAPH_ARGS = ("uc-camera-recording.yaml", "cam-rec-r1-fhd30-vdis")


def _level1_view():
    return golden.service._project_semantic_level1(golden._graph(*GRAPH_ARGS))


def test_vdis_m2m_edges_declare_dma_pairs_and_memory():
    view = _level1_view()
    by_buffer = {edge.data.buffer_ref: edge.data for edge in view.edges if edge.data.buffer_ref}
    pyramid = by_buffer["PYRAMID_L0"]
    assert [(pair.src, pair.dst) for pair in pyramid.port_pairs] == [("MLSC_W_GLPG0_Y", "MTNR0_RDMA_CUR_L0_Y")]
    assert (pyramid.memory.width, pyramid.memory.height) == (4080, 2296)
    assert pyramid.memory.format == "Y"
    assert by_buffer["MCSC_PREVIEW"].port_pairs[0].src == "MCSC_WDMA_W0"
    lme = by_buffer["LME_INPUT"]
    assert [(pair.src, pair.dst) for pair in lme.port_pairs] == [("MLSC_W_LMEDS", "LME_RDMA_CACHE_IN_0")]


def test_vdis_scale_and_crop_facts_are_explicit():
    view = _level1_view()
    ops = {node.data.id: node.data.active_operations for node in view.nodes if node.data.active_operations}
    assert all(not op.scale for node_id, op in ops.items() if "yuvsc" in node_id)
    assert any(op.scale for node_id, op in ops.items() if "mcsc" in node_id)
    gdc_ops = [op for node_id, op in ops.items() if "gdc" in node_id]
    assert len(gdc_ops) == 2 and all(op.crop for op in gdc_ops)


def test_vdis_pyramid_preserves_sensor_size_and_five_layers():
    view = _level1_view()
    by_buffer = {edge.data.buffer_ref: edge.data for edge in view.edges if edge.data.buffer_ref}
    assert "CSISPDP_3AA_BUF" not in by_buffer
    for layer in range(5):
        memory = by_buffer[f"PYRAMID_L{layer}"].memory
        factor = 2 ** layer
        assert (memory.width, memory.height) == ((4080 + factor - 1) // factor, (2296 + factor - 1) // factor)


def test_statistics_with_unknown_size_do_not_inherit_record_resolution():
    from scenario_db.view.level0_v2 import _buffer_size
    graph = golden._graph(*GRAPH_ARGS)
    view = golden.service._project_semantic_level1(graph)
    for name in ("RGBP_DRC", "MLSC_SVHIST"):
        edge = next(e.data for e in view.edges if e.data.buffer_ref == name)
        assert edge.memory.width is None and edge.memory.height is None
        assert _buffer_size(graph, graph.scenario.pipeline["buffers"][name]) == (None, None)
