"""Port-pair wiring and the full-module (expand=all) Level 2 view."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_view_projection_golden as golden  # noqa: E402

from scenario_db.models.definition.usecase import PipelineEdge  # noqa: E402
from scenario_db.view.graph_utils import edge_port_pairs  # noqa: E402

pytestmark = pytest.mark.unit

GRAPH_ARGS = ("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")


def test_pipeline_edge_accepts_port_pairs():
    edge = PipelineEdge.model_validate(
        {
            "from": "csispdp",
            "to": "n3aa",
            "type": "M2M",
            "buffer": "CSISPDP_3AA_BUF",
            "port_pairs": [{"src": "CSISPDP_WDMA", "dst": "3AA_RDMA"}],
        }
    )
    assert edge.port_pairs[0].src == "CSISPDP_WDMA"
    assert edge.port_pairs[0].dst == "3AA_RDMA"


def test_edge_port_pairs_drops_malformed_entries():
    edge = {"port_pairs": [{"src": "A", "dst": "B"}, {"src": "", "dst": "X"}, "junk", {"src": "C"}]}
    assert edge_port_pairs(edge) == [{"src": "A", "dst": "B"}]


def test_level1_projection_exposes_port_pairs():
    view = golden.service._project_semantic_level1(golden._graph(*GRAPH_ARGS))

    pairs = {
        (pair.src, pair.dst)
        for edge in view.edges
        for pair in edge.data.port_pairs
    }
    assert ("CSISPDP_WDMA", "3AA_RDMA") in pairs
    assert ("MCSC_WDMA_PREV", "GDC_M_RDMA") in pairs


def test_level2_port_pair_routes_edge_to_declared_wdma_module():
    view = golden.service._project_drilldown(golden._graph(*GRAPH_ARGS), "csispdp")

    write_edges = [edge for edge in view.edges if edge.data.buffer_ref == "CSISPDP_3AA_BUF"]
    assert write_edges, "expected the CSISPDP write edge"
    assert write_edges[0].data.source == "mod-csispdp-csispdp-wdma"
    assert write_edges[0].data.port_pairs[0].src == "CSISPDP_WDMA"


def test_expand_all_builds_full_module_view():
    view = golden.service._project_drilldown(golden._graph(*GRAPH_ARGS), "all")

    assert view.mode == "drilldown:all"
    module_nodes = [node for node in view.nodes if node.data.module_kind]
    package_count = len({node.data.parent for node in module_nodes if node.data.parent})
    assert len(module_nodes) >= 10
    assert package_count >= 5  # multiple IPs expanded on one canvas
    assert any(node.data.type == "buffer" for node in view.nodes)
