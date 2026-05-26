"""Shared ViewResponse element factories."""
from __future__ import annotations

from scenario_db.api.schemas.view import EdgeData, EdgeElement, NodeData, NodeElement

def _n(nid: str, label: str, ntype: str, layer: str,
       x: float, y: float, **kwargs) -> NodeElement:
    data = NodeData(id=nid, label=label, type=ntype, layer=layer, **kwargs)
    return NodeElement(data=data, position={"x": x, "y": y})

def _e(eid: str, src: str, tgt: str, flow_type: str, **kwargs) -> EdgeElement:
    data = EdgeData(id=eid, source=src, target=tgt, flow_type=flow_type, **kwargs)
    return EdgeElement(data=data)
