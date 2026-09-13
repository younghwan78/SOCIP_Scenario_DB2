"""Explicit byte-stream and software memory traffic; no image-size surrogate."""
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.models import PortTransferSpec, PortType


def supplemental_transfers(graph: CanonicalScenarioGraph) -> list[PortTransferSpec]:
    transfers = []
    conditions = graph.variant.design_conditions or {}
    for node in graph.pipeline_nodes:
        config = (graph.variant.node_configs or {}).get(node["id"], {})
        for item in config.get("memory_io", []):
            if item.get("direction") not in {"read", "write"} or item.get("copies", 1) <= 0:
                raise ValueError(f"{node['id']}: memory_io needs read/write direction and positive copies")
            transfers.append(PortTransferSpec(
                node_id=node["id"], ip_ref=node["ip_ref"], hw_name=node["id"].upper(),
                port=item["port"], port_type=PortType.DMA_READ if item["direction"] == "read" else PortType.DMA_WRITE,
                width=item.get("width", 0), height=item.get("height", 0),
                format=item.get("format", "BITSTREAM"), bitwidth=item.get("bitwidth", 8),
                bitrate_mbps=conditions[item["bitrate_condition"]] if item.get("bitrate_condition") else None,
                r_w_rate=item.get("copies", 1),
            ))
    return transfers
