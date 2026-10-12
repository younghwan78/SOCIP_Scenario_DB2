"""Memory power levers of one (resolved) variant: LLC-resident buffers, compressed buffers, vOTF links.

Same rules as the React pipeline model: the scenario buffer merged with the variant's buffer_overrides,
``placement.llc_allocated`` for LLC, any non-off compression mode for SBWC/AFBC, ``type: vOTF`` edges.
Buffers / edges touching a disabled node are not counted.
"""

from __future__ import annotations

import math
from typing import Any

from scenario_db.sim.bw_calc import compression_enabled
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.transfers import enabled


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (over or {}).items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def memory_levers(pipeline: dict[str, Any] | None, buffer_overrides: dict[str, Any] | None,
                  disabled_nodes: list[str] | set[str] | None = None, *,
                  node_configs: dict[str, Any] | None = None) -> dict[str, Any]:
    pipeline = pipeline or {}
    off = {str(n) for n in disabled_nodes or []}
    edges = [e for e in pipeline.get("edges") or [] if isinstance(e, dict)]
    live = [e for e in edges if str(edge_source(e)) not in off and str(edge_target(e)) not in off]
    active = {str(n.get("id")) for n in pipeline.get("nodes") or [] if str(n.get("id")) not in off}
    live = [e for e in live if edge_type(e) == "M2M" or edge_type(e) == "VOTF"]
    used: set[str] = {str(e.get("buffer")) for e in live if e.get("buffer") and edge_type(e) == "M2M"}
    buffers = pipeline.get("buffers") or {}
    llc: list[str] = []
    comp: list[str] = []
    weights: list[float] = []
    for bid in sorted(set(buffers) | set(buffer_overrides or {})):
        spec = _merge(buffers.get(bid) or {}, (buffer_overrides or {}).get(bid) or {})
        owner = (spec.get("history") or {}).get("node_id") or (spec.get("dma") or {}).get("node_id")
        if bid not in used and not (owner and str(owner) not in off and ("nodes" not in pipeline or str(owner) in active)):
            continue
        if bid not in used and not spec.get("history"):
            dma = spec.get("dma") or {}
            flag = dma.get("activation_flag")
            if not enabled(dma.get("enabled", True)) or (flag and not enabled(((node_configs or {}).get(owner) or {}).get(flag, False))):
                continue
        placement = spec.get("placement") or {}
        if placement.get("llc_allocated") is True:
            llc.append(bid)
            w = placement.get("llc_weight")
            if isinstance(w, (int, float)) and 0 < w <= 1:
                weights.append(float(w))
        if compression_enabled(spec.get("compression")):
            comp.append(bid)
    votf = [f"{edge_source(e)}->{edge_target(e)}" for e in live if edge_type(e) == "VOTF"]
    # LLC size: llc_allocation_mb is the owner's partition (shared by its buffers) -> max per owner, summed
    part: dict[str, float] = {}
    unsized: set[str] = set()
    for bid in llc:
        pl = _merge(buffers.get(bid) or {}, (buffer_overrides or {}).get(bid) or {}).get("placement") or {}
        mb = pl.get("llc_allocation_mb")
        owner = str(pl.get("allocation_owner") or bid)
        if isinstance(mb, (int, float)) and math.isfinite(mb) and mb > 0:
            part[owner] = max(part.get(owner, 0.0), float(mb))
        else:
            unsized.add(owner)
    # compressed DMA channels: every WDMA/RDMA port that moves a compressed buffer
    comp_ports: set[tuple[str, str]] = set()
    for bid in comp:
        spec = _merge(buffers.get(bid) or {}, (buffer_overrides or {}).get(bid) or {})
        for e in live:
            if str(e.get("buffer") or "") != bid or edge_type(e) != "M2M":
                continue
            pairs = e.get("port_pairs") or []
            if pairs:
                for pair in pairs:
                    comp_ports.update((str(node), str(pair[k])) for k, node in (("src", edge_source(e)), ("dst", edge_target(e))) if pair.get(k))
            else:
                comp_ports.update({(str(edge_source(e)), f"{bid}_WDMA"), (str(edge_target(e)), f"{bid}_RDMA")})
        for key in ("history", "dma"):
            ep = spec.get(key) or {}
            node = str(ep.get("node_id") or "")
            flag = ep.get("activation_flag")
            if not node or node in off or ("nodes" in pipeline and node not in active):
                continue
            if key == "dma" and (not enabled(ep.get("enabled", True)) or (flag and not enabled(((node_configs or {}).get(node) or {}).get(flag, False)))):
                continue
            comp_ports.update((node, str(x)) for x in (ep.get("read_ports") or []) + (ep.get("write_ports") or []))
    return {"llc": llc, "compressed": comp, "votf": votf, "llc_weight_min": min(weights) if weights else None,
            "llc_mb": sum(part.values()) if part else None, "llc_owners": sorted(part), "llc_unsized": len(unsized - part.keys()),
            "compressed_dma": len(comp_ports)}
