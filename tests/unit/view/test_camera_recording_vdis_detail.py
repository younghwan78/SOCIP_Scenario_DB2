"""Legacy-density validation for the cam-rec-r1-fhd30-vdis projection."""
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

    yuvsc = by_buffer["YUVSC_MTNR_BUF"]
    assert [(pair.src, pair.dst) for pair in yuvsc.port_pairs] == [("YUVSC_WDMA", "MTNR_RDMA")]
    assert (yuvsc.memory.width, yuvsc.memory.height) == (1920, 1080)
    assert yuvsc.memory.format == "YUV422"

    eis_in = by_buffer["MCSC_WDMA_EIS_BUF"]
    assert eis_in.port_pairs[0].src == "MCSC_WDMA_EIS"

    lme = by_buffer["LME_MTNR_BUF"]
    assert [(pair.src, pair.dst) for pair in lme.port_pairs] == [("LME_WDMA", "MTNR_MV_RDMA")]


def test_vdis_scale_and_crop_facts_are_explicit():
    view = _level1_view()
    ops = {node.data.id: node.data.active_operations for node in view.nodes if node.data.active_operations}

    yuvsc_ops = next(op for node_id, op in ops.items() if "yuvsc" in node_id)
    assert yuvsc_ops.scale is True
    assert yuvsc_ops.scale_from == "4000x3000"
    assert yuvsc_ops.scale_to == "1920x1080"

    gdc_ops = [op for node_id, op in ops.items() if "gdc" in node_id]
    assert gdc_ops and all(op.crop for op in gdc_ops)


def test_vdis_raw_buffer_declares_sensor_size():
    view = _level1_view()
    raw_edges = [edge.data for edge in view.edges if edge.data.buffer_ref == "CSISPDP_3AA_BUF"]
    assert raw_edges
    memory = raw_edges[0].memory
    assert (memory.width, memory.height) == (4000, 3000)
    assert memory.compression == "COMP_BAYER_LOSSLESS"
