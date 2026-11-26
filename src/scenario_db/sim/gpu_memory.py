"""M-7: the GPU's own DRAM traffic (L0 ``mb_per_frame``) and the MIF min-lock floor its clock sets.

- ``node_configs.<gpu>.sim.workload.mb_per_frame: {read, write, llc_weight}`` (MB / frame, DRAM side, after
  compression) becomes two DMA ports ``GPU_WORKLOAD_RD`` / ``GPU_WORKLOAD_WR`` at the run fps. The scenario's
  pipeline buffers (framebuffer ``GPU_DPU_BUF`` …) keep their own ports and are not in this volume.
- The kernel ties the MIF minimum to the GPU clock (``dvfs_model.mif_min_lock_khz`` of the GPU catalog:
  ``{base, '<gpu khz>': <mif khz>, ...}``). The floor of a GPU clock f is the value of the largest key <= f
  (``base`` below the smallest key).
- Timing Budget (where the GPU clock exists: its domain load) reports ``bw.mif``. With the ``mif-linear`` BW
  model the MIF level is max(governor, QoS lock, floor), and only what the floor adds (base(level) -
  base(level without floor)) is added to the BW power. With other BW models the floor is reported only.

Opt-in: a GPU node whose ``sim.workload`` mapping declares ``frame_time``, ``mb_per_frame`` or ``mif_floor``
(WorkloadSpec); ``mif_floor: none`` turns the floor off.
"""

from __future__ import annotations

from typing import Any

from scenario_db.sim.models import IPWorkload, PortTransferSpec, PortType
from scenario_db.sim.workload_spec import WorkloadSpec, workload_spec

MODEL = "gpu-mif-floor-v1"
OPT_IN_KEYS = {"frame_time", "mb_per_frame", "mif_floor"}
PORTS = (("GPU_WORKLOAD_RD", PortType.DMA_READ, "read"), ("GPU_WORKLOAD_WR", PortType.DMA_WRITE, "write"))


def _is_gpu(graph, node: dict) -> bool:
    ip = (getattr(graph, "ip_catalog", None) or {}).get(str(node.get("ip_ref") or ""))
    text = " ".join(str(x or "").lower() for x in (getattr(ip, "category", None), node.get("ip_ref"), node.get("role")))
    return "gpu" in text


def gpu_workloads(graph, active: set[str]) -> dict[str, WorkloadSpec]:
    """``{node: WorkloadSpec}`` of the active GPU nodes whose ``sim.workload`` is a mapping."""
    configs = getattr(graph.variant, "node_configs", None) or {}
    out: dict[str, WorkloadSpec] = {}
    for node in getattr(graph, "pipeline_nodes", None) or []:
        nid = str(node.get("id") or "")
        config = configs.get(nid)
        sim = config.get("sim") if isinstance(config, dict) else None
        raw = sim.get("workload") if isinstance(sim, dict) else None
        # opt-in: a mapping that declares a field these models read (other mappings are not parsed, as in R-5a)
        if nid in active and _is_gpu(graph, node) and isinstance(raw, dict) and OPT_IN_KEYS & set(raw):
            spec = workload_spec(sim)
            if spec is not None:
                out[nid] = spec
    return out


def gpu_workload_transfers(graph, nodes: dict[str, IPWorkload]) -> list[PortTransferSpec]:
    """The declared GPU workload traffic of the GPU nodes among ``nodes`` (workloads or SW-timed stand-ins)."""
    specs: list[PortTransferSpec] = []
    for nid, spec in gpu_workloads(graph, set(nodes)).items():
        traffic = spec.mb_per_frame
        if traffic is None:
            continue
        node = nodes[nid]
        llc = traffic.llc_weight is not None
        for port, direction, key in PORTS:
            mb = float(getattr(traffic, key))
            if mb <= 0:
                continue
            specs.append(PortTransferSpec(
                node_id=nid, ip_ref=node.ip_ref, hw_name=node.hw_name, port=port, port_type=direction,
                mb_per_frame=mb, width=0, height=0, format="GPU_WORKLOAD",
                llc_enabled=llc, llc_weight=traffic.llc_weight if llc else 1.0))
    return specs


def mif_floor_khz(table: Any, gpu_khz: float) -> tuple[float, str] | None:
    """(floor kHz, the key it came from) of ``mif_min_lock_khz`` at a GPU clock; None without a usable table."""
    if not isinstance(table, dict) or not table:
        return None
    steps: list[tuple[float, float]] = []
    for key, value in table.items():
        if str(key) == "base":
            continue
        try:
            steps.append((float(key), float(value)))
        except (TypeError, ValueError):
            continue
    steps.sort()
    hit = [s for s in steps if s[0] <= gpu_khz + 1e-6]
    if hit:
        return hit[-1][1], f"{hit[-1][0]:g}"
    base = table.get("base")
    return (float(base), "base") if isinstance(base, (int, float)) and not isinstance(base, bool) else None


def _min_lock_table(graph, node: str) -> Any:
    ref = next((n.get("ip_ref") for n in graph.pipeline_nodes if str(n.get("id")) == node), "")
    ip = (getattr(graph, "ip_catalog", None) or {}).get(str(ref or ""))
    return ((getattr(ip, "capabilities", None) or {}).get("dvfs_model") or {}).get("mif_min_lock_khz")


def mif_inputs(graph) -> dict[str, Any]:
    """What the MIF floor reads beyond the simulation inputs, for the condition hash; {} when not declared."""
    nodes = getattr(graph, "pipeline_nodes", None) or []
    configs = getattr(graph.variant, "node_configs", None) or {}
    out: dict[str, Any] = {}
    for spec_node in gpu_workloads(graph, {str(n.get("id")) for n in nodes}):
        raw = ((configs.get(spec_node) or {}).get("sim") or {}).get("workload")
        out[spec_node] = {"model": MODEL, "workload": raw, "min_lock_khz": _min_lock_table(graph, spec_node)}
    return out


def mif_report(graph, active: set[str], domain: dict[str, dict], result, inputs) -> dict[str, Any] | None:
    """``bw.mif`` of a Timing Budget run (None when no active GPU declares a workload mapping)."""
    from scenario_db.sim.bw_power import bw_model_from_config, dma_context

    gpus = gpu_workloads(graph, active)
    if not gpus:
        return None
    node, spec = next(iter(gpus.items()))
    est = domain.get(node) or {}
    gpu_mhz = est.get("freq_mhz")
    out: dict[str, Any] = {"model": MODEL, "node": node, "gpu_mhz": gpu_mhz, "source": spec.mif_floor}
    if spec.mb_per_frame is not None:
        out["gpu_workload_mbs"] = {d.port: round(d.bw_mbs, 3) for d in result.dma_breakdown
                                   if d.node_id == node and d.port in {p for p, _, _ in PORTS}}
    floor_mhz = None
    if spec.mif_floor == "catalog":
        table = _min_lock_table(graph, node)
        if not gpu_mhz:
            out["status"] = "no_gpu_clock"
            out["reason"] = f"{node}: the MIF floor needs the GPU clock (a domain load)"
        else:
            hit = mif_floor_khz(table, float(gpu_mhz) * 1000.0)
            if hit is None:
                out["status"] = "no_table"
                out["reason"] = f"{node}: the GPU catalog has no dvfs_model.mif_min_lock_khz"
            else:
                floor_mhz = hit[0] / 1000.0
                out.update({"floor_mhz": floor_mhz, "floor_key_khz": hit[1], "status": "ok"})
    else:
        out["status"] = "off"
    run_config = inputs.config
    model = bw_model_from_config(run_config)
    state_of = getattr(model, "mif_state", None)
    if state_of is None:
        out["bw_model"] = getattr(model, "model_id", None) or "default"
        out["applied"] = False          # no MIF level in this BW model: the floor is reported only
        return out
    sn, rail = inputs.dvfs_sn, run_config.memory_rail
    plain = state_of(dma_context(result.dma_breakdown, memory_rail=rail, dvfs_sn=sn))
    state = plain if floor_mhz is None else state_of(
        dma_context(result.dma_breakdown, memory_rail=rail, dvfs_sn=sn, min_lock_mhz=floor_mhz))
    extra = float(state["base_mw"]) - float(plain["base_mw"])
    out.update({"bw_model": model.model_id, "applied": floor_mhz is not None,  # type: ignore[union-attr]
                "level_mhz": state["mif_mhz"], "level_reason": state["reason"], "base_mw": state["base_mw"],
                "level_without_floor_mhz": plain["mif_mhz"], "dram_mbs": state["dram_mbs"],
                "utilization": state["utilization"], "floor_extra_mw": round(extra, 6)})
    if spec.mb_per_frame is not None and float(state.get("other_masters_mbs") or 0) > 0:
        out["double_count"] = (f"power params other_masters_mbs {state['other_masters_mbs']:g} MB/s (unmodelled "
                               f"masters, GPU included) is added on top of the declared GPU workload traffic")
    if state.get("min_lock_above_top"):
        out["warning"] = (f"MIF floor {floor_mhz:g} MHz is above the highest modelled MIF level "
                          f"{state['mif_mhz']:g} MHz (power params mif_opps)")
    return out
