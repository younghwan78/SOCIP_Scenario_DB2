from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories.scenario_graph import _is_sensor_node
from scenario_db.view.level0_v2 import _resource_kind
from scenario_db.view.service import _architecture_resource_kind
from scenario_db.write.service import _is_sw_node, _node_class


def _graph(ip_catalog: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(ip_catalog=ip_catalog or {})


def test_explicit_node_class_overrides_sw_token_heuristic():
    """Review 5.3: schema-declared node_class beats id/token matching.
    'cpu' token would classify as sw, but node_class says hw."""
    node = {"id": "cpu_offload", "node_type": "cpu task", "node_class": "hw", "ip_ref": "ip-x"}

    assert _is_sw_node(node) is False
    assert _node_class(None, node) == "hw"


def test_explicit_node_class_sw_wins_over_hw_looking_node():
    node = {"id": "enc0", "ip_ref": "ip-mfc-v14", "node_class": "sw"}

    assert _is_sw_node(node) is True
    assert _node_class(None, node) == "sw"


def test_node_class_heuristic_still_applies_without_explicit_field():
    assert _is_sw_node({"id": "hal0", "layer": "hal"}) is True
    assert _is_sw_node({"id": "isp0", "ip_ref": "ip-isp-v12"}) is False


def test_invalid_explicit_node_class_falls_back_to_heuristic():
    node = {"id": "hal0", "layer": "hal", "node_class": "bogus"}

    assert _is_sw_node(node) is True


def test_architecture_resource_kind_prefers_explicit_field():
    # 'sensor' in the id would classify as sensor, but the schema says isp.
    node = {"id": "sensor_isp_bridge", "resource_kind": "isp"}

    assert _architecture_resource_kind(_graph(), node) == "isp"


def test_level0_resource_kind_prefers_explicit_field():
    node = {"id": "mem_streamer", "resource_kind": "npu"}

    assert _resource_kind(_graph(), node) == "npu"


def test_is_sensor_node_prefers_explicit_field():
    sensor_by_field = {"id": "front_module", "resource_kind": "sensor"}
    not_sensor_despite_token = {"id": "sensor_hub_isp", "resource_kind": "isp"}

    assert _is_sensor_node(_graph(), sensor_by_field) is True
    assert _is_sensor_node(_graph(), not_sensor_despite_token) is False


def test_is_sensor_node_heuristic_fallback_unchanged():
    assert _is_sensor_node(_graph(), {"id": "sensor0", "ip_ref": "ip-imx-v1"}) is True
    assert _is_sensor_node(_graph(), {"id": "isp0", "ip_ref": "ip-isp-v12"}) is False
