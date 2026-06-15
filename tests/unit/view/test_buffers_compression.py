from __future__ import annotations

import pytest

from scenario_db.view.buffers import _compression_for_buffer, display_compression


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("COMP_OFF", "COMP_OFF"),
    ("none", "COMP_OFF"),
    ("disable", "COMP_OFF"),
    ("off", "COMP_OFF"),
    ("COMP_YUV_LOSSY", "COMP_YUV_LOSSY"),
    ("COMP_BAYER_LOSSLESS", "COMP_BAYER_LOSSLESS"),
])
def test_display_compression_unifies_off_spellings(value, expected):
    assert display_compression(value) == expected


class _Ip:
    def __init__(self, capabilities):
        self.capabilities = capabilities


class _Graph:
    def __init__(self, edges, nodes, ip_catalog):
        self.pipeline_edges = edges
        self._nodes = nodes
        self.ip_catalog = ip_catalog

    def node_by_id(self, node_id):
        return self._nodes.get(node_id)


def _graph(ip_caps):
    return _Graph(
        edges=[{"from": "mcsc0", "to": "mfc", "type": "M2M", "buffer": "REC"}],
        nodes={"mcsc0": {"id": "mcsc0", "ip_ref": "ip-mcsc"}},
        ip_catalog={"ip-mcsc": _Ip(ip_caps)},
    )


def test_compression_for_buffer_uses_producing_ip_top_level():
    graph = _graph({"supported_features": {"compression": ["COMP_OFF", "COMP_YUV_LOSSY"]}})
    # COMP_OFF is skipped in favour of a real mode.
    assert _compression_for_buffer(graph, "REC") == "COMP_YUV_LOSSY"


def test_compression_for_buffer_uses_per_dma_modules():
    graph = _graph({"properties": {"modules": [
        {"name": "MCSC_WDMA", "type": "DMA", "supported_compressions": ["COMP_OFF", "COMP_YUV_LOSSLESS"]},
    ]}})
    assert _compression_for_buffer(graph, "REC") == "COMP_YUV_LOSSLESS"


def test_compression_for_buffer_none_when_unknown_buffer():
    graph = _graph({"supported_features": {"compression": ["COMP_YUV_LOSSY"]}})
    assert _compression_for_buffer(graph, "DOES_NOT_EXIST") is None


def test_compression_for_buffer_none_when_producer_declares_nothing():
    graph = _graph({})
    assert _compression_for_buffer(graph, "REC") is None
