"""Unit tests for the diagram click selection bridge."""
from __future__ import annotations

import pytest

from dashboard.components.graph_selection_bridge import bridge_available, normalize_graph_selection

pytestmark = pytest.mark.unit


def test_bridge_assets_are_packaged():
    assert bridge_available() is True


def test_normalize_accepts_valid_payload():
    assert normalize_graph_selection({"id": "ip-mcsc", "kind": "node", "label": "MCSC", "seq": 42}) == {
        "id": "ip-mcsc",
        "kind": "node",
        "label": "MCSC",
        "seq": 42,
    }


def test_normalize_defaults_unknown_kind_to_node_and_label_to_id():
    normalized = normalize_graph_selection({"id": "e-1", "kind": "weird"})
    assert normalized == {"id": "e-1", "kind": "node", "label": "e-1", "seq": 0}


def test_normalize_rejects_empty_or_invalid():
    assert normalize_graph_selection(None) is None
    assert normalize_graph_selection("x") is None
    assert normalize_graph_selection({"id": " "}) is None
