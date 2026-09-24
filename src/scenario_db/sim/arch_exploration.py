"""Architecture exploration over a scenario variant.

Axes
- SW timing statistic (min/mean/max) x next-project SW growth scale -> simulated
  (stage timing budget, ``timing_budget.analyze_timing_budget``)
- DVFS headroom: each DVFS domain at its resolved level or up to ``k`` faster
  levels -> analytic (IP power scales with (V/V0)^2, clock only gets faster)
- Buffer compression per M2M/history buffer (OFF or a lossy/lossless mode)
  -> analytic (per-port BW is linear in comp_ratio; the DMA transfer set is
  rebuilt by the real adapter with a ``buffer_overrides`` patch)

Every combination is enumerated for the power/BW range. The recommended case
is the lowest total power eligible case at the objective statistic/scale; it
is re-simulated with the compression/DVFS overrides applied, and the analytic
and simulated totals are compared (``verified``).

Power = CPU(SW) + HW(IP core) + BW(DMA). MIF DVFS is not modeled.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, is_dataclass, replace
from itertools import product
from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.bw_calc import calc_port_bw, compression_enabled, normalize_compression
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.models import DVFSTable, SimulationRunConfig
from scenario_db.sim.power_model import resolve_power_model
from scenario_db.sim.timing_budget import (
    Statistic,
    TimingBudgetOptions,
    analyze_timing_budget,
)
from scenario_db.sim.transfers import compression_catalog

ENGINE_REV = "arch-exploration/1"
V_REF_MV = 710.0
DEFAULT_RATIO = {"LOSSY": 0.5}
_BAYER_RE = re.compile(r"BAYER|RAW|BGGR|RGGB|GRBG|GBRG|PDAF", re.I)


# ------------------------------------------------------------------- options
CompressionMode = Literal["lossy", "lossless"]


def _lossy() -> list[CompressionMode]:
    return ["lossy"]


def _mean_max() -> list[Statistic]:
    return ["mean", "max"]


class CompressionAxis(BaseScenarioModel):
    enabled: bool = True
    modes: list[CompressionMode] = Field(default_factory=_lossy)
    # mode name (e.g. COMP_YUV_LOSSLESS) -> remaining-BW fraction; beats the SoC catalog
    ratio_overrides: dict[str, float] = Field(default_factory=dict)
    buffers: list[str] | None = None
    include_unsupported: bool = False
    max_buffers: int = Field(default=8, ge=0, le=12)
    min_saving_mbs: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _ratios(self) -> CompressionAxis:
        if any(not (0 < v <= 1) for v in self.ratio_overrides.values()):
            raise ValueError("compression ratio_overrides must be in (0, 1]")
        return self


class ExplorationAxes(BaseScenarioModel):
    statistics: list[Statistic] = Field(default_factory=_mean_max, min_length=1)
    runtime_scales: list[float] = Field(default_factory=lambda: [1.0, 1.1, 1.2], min_length=1, max_length=8)
    eis: Literal["auto", "on", "off"] = "auto"
    dvfs_headroom_levels: int = Field(default=1, ge=0, le=3)
    compression: CompressionAxis = Field(default_factory=CompressionAxis)

    @model_validator(mode="after")
    def _scales(self) -> ExplorationAxes:
        if any(not math.isfinite(v) or v <= 0 or v > 10 for v in self.runtime_scales):
            raise ValueError("runtime_scales must be in (0, 10]")
        return self


class ExplorationConstraints(BaseScenarioModel):
    require_intervals: bool = True
    allow_clock_up: bool = True
    allow_lossy: bool = True
    # an all-zero IP power model cannot be compared -> never "spec OK"
    require_power_model: bool = True
    power_budget_mw: float | None = Field(default=None, gt=0)
    bw_budget_mbs: float | None = Field(default=None, gt=0)


class ExplorationObjective(BaseScenarioModel):
    statistic: Statistic = "max"
    runtime_scale: float = Field(default=1.0, gt=0, le=10)
    tie_pct: float = Field(default=1.0, ge=0, le=10)


class ArchExplorationSpec(BaseScenarioModel):
    axes: ExplorationAxes = Field(default_factory=ExplorationAxes)
    constraints: ExplorationConstraints = Field(default_factory=ExplorationConstraints)
    objective: ExplorationObjective = Field(default_factory=ExplorationObjective)
    timing: TimingBudgetOptions = Field(default_factory=TimingBudgetOptions)
    top_n: int = Field(default=5, ge=1, le=20)
    max_cases_per_variant: int = Field(default=200_000, ge=1)
    verify: bool = True


# ------------------------------------------------------------------- public
def explore_variant(
    graph,
    spec: ArchExplorationSpec | None = None,
    *,
    config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None,
) -> dict[str, Any]:
    spec = spec or ArchExplorationSpec()
    tables = dvfs_tables or {}
    config = config or SimulationRunConfig()
    axes, obj = spec.axes, spec.objective
    stats = list(dict.fromkeys([*axes.statistics, obj.statistic]))
    scales = sorted(set(axes.runtime_scales) | {obj.runtime_scale})

    slices: list[dict[str, Any]] = []
    for stat in stats:
        for scale in scales:
            opts = spec.timing.model_copy(
                update={"statistic": stat, "runtime_scale": scale, "eis": axes.eis, "include_whatif": False}
            )
            slices.append(_slice(analyze_timing_budget(graph, opts, config=config, dvfs_tables=tables), stat, scale))
    obj_slice = next(s for s in slices if s["statistic"] == obj.statistic and s["runtime_scale"] == obj.runtime_scale)

    buffers = compression_candidates(graph, axes.compression, config) if axes.compression.enabled else []
    active = [b for b in buffers if b["selectable"]][: axes.compression.max_buffers]
    explored = {b["buffer"] for b in active}
    for b in buffers:
        b["explored"] = b["buffer"] in explored
        if b["selectable"] and not b["explored"]:
            b["skip_reason"] = f"outside top {axes.compression.max_buffers} savings (max_buffers)"
    for s in slices:
        s["domains"] = dvfs_options(s["ips"], tables, axes.dvfs_headroom_levels, config.asv_group)

    n_comp = 2 ** len(active)
    n_dvfs = math.prod(len(d["options"]) for d in obj_slice["domains"]) if obj_slice["domains"] else 1
    if len(slices) * n_comp * n_dvfs > spec.max_cases_per_variant:
        raise ValueError(
            f"exploration exceeds {spec.max_cases_per_variant} cases "
            f"({len(slices)} SW x {n_comp} compression x {n_dvfs} DVFS); reduce axes"
        )

    comp_sets = _subset_sums(active)
    dist: dict[str, list[float]] = {k: [] for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_mbs")}
    eligible_count = 0
    cases_obj: list[dict[str, Any]] = []
    for s in slices:
        dv_sets = _dvfs_sets(s["domains"])
        ok_slice, _ = _slice_ok(s, spec.constraints)
        for cset in comp_sets:
            for dset in dv_sets:
                case = _case(s, cset, dset)
                case["eligible"] = ok_slice and _case_ok(case, spec.constraints)
                for k in dist:
                    dist[k].append(case[k])
                eligible_count += case["eligible"]
                if s is obj_slice:
                    cases_obj.append(case)

    ranked = _rank([c for c in cases_obj if c["eligible"]], obj.tie_pct)
    recommended = ranked[0] if ranked else None
    alternatives = _distinct(ranked[1:], spec.top_n, seen={round(recommended["total_mw"], 1)} if recommended else None)
    baseline = next(c for c in cases_obj if not c["compression"] and not c["dvfs_raise"])
    ok_obj, obj_reasons = _slice_ok(obj_slice, spec.constraints)
    if recommended is not None and spec.verify:
        recommended["verified"] = _verify(graph, spec, config, tables, recommended, buffers)

    summary = {
        "engine_rev": ENGINE_REV,
        "scenario_id": graph.scenario.id,
        "variant_id": graph.variant.id,
        "design_conditions": _jsonable(getattr(graph.variant, "design_conditions", None) or {}),
        "fps": obj_slice["fps"],
        "period_ms": obj_slice["period_ms"],
        "eis_on": obj_slice["eis_on"],
        "mfc_dual": obj_slice["mfc_dual"],
        "spec_ok": recommended is not None,
        "spec_reasons": [] if recommended is not None else (obj_reasons or ["no eligible combination"]),
        "objective": obj.model_dump(),
        "counts": {
            "cases": len(dist["total_mw"]),
            "eligible": eligible_count,
            "sw_slices": len(slices),
            "compression_sets": n_comp,
            "dvfs_sets": n_dvfs,
        },
        "distribution": {k: quantiles(v) for k, v in dist.items()},
        "baseline": _public_case(baseline),
        "recommended": _public_case(recommended) if recommended else None,
        "alternatives": [_public_case(c) for c in alternatives],
        "slices": [_slice_public(s) for s in slices],
        "buffers": buffers,
        "domains": obj_slice["domains"],
        "axis_spread": _axis_spread(slices, obj_slice, comp_sets, obj),
        "sw_margin": sw_margin(slices, obj_slice, obj),
        # objective slice keeps IP rows + DVFS options: promotion builds the frozen payload from it
        "objective_slice": {k: v for k, v in obj_slice.items() if k != "warnings"},
        "coverage": {
            "zero_power_ips": obj_slice["zero_power_ips"],
            "hw_power_modeled": obj_slice["power"]["hw_mw"] > 0,
            "cpu_power_modeled": obj_slice["power"]["cpu_mw"] > 0,
        },
        "warnings": obj_slice["warnings"][:20],
    }
    summary["input_hash"] = input_hash(graph, spec, config, tables)
    return summary


# ------------------------------------------------------------------- slices
def _slice(report: dict[str, Any], stat: str, scale: float) -> dict[str, Any]:
    ips = []
    for ip in report["ips"]:
        v = float(ip.get("voltage_mv") or 0.0)
        p = float(ip.get("power_mw") or 0.0)
        ips.append({
            "node": ip["node"],
            "stage": ip["stage"],
            "dvfs_group": ip["dvfs_group"],
            "cores": ip["cores"],
            "rule_clock_mhz": ip["rule_clock_mhz"],
            "required_clock_mhz": ip["required_clock_mhz"],
            "set_clock_mhz": ip["set_clock_mhz"],
            "dvfs_level": ip["dvfs_level"],
            "voltage_mv": v,
            "power_mw": p,
            # IP power = activity x (V/710)^2 (power model v1-vfps) -> attribution factor
            "activity_mw": p / (v / V_REF_MV) ** 2 if v > 0 else p,
            "hw_ms": ip["hw_ms"],
            "feasible": ip["feasible"],
        })
    st = {s["id"]: s for s in report["stages"]}
    return {
        "statistic": stat,
        "runtime_scale": scale,
        "fps": report["fps"],
        "period_ms": report["period_ms"],
        "eis_on": report["eis"]["on"],
        "mfc_dual": bool(report.get("mfc_dual")),
        "verdict": report["verdict"],
        "intervals_ok": bool(report["intervals"]["ok"]),
        "intervals": {k: report["intervals"][k]["max_ms"] for k in ("preview", "video")},
        "latency": report["latency"],
        "power": {k: report["power"][k] for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_hw_mw", "bw_sw_mw")},
        "cpu_by_task": report["power"]["cpu_by_task"],
        "zero_power_ips": report["power"].get("zero_power_ips", []),
        "bw": {k: report["bw"][k] for k in ("total_mbs", "hw_mbs", "sw_mbs")},
        "stages": {
            k: {f: st[k][f] for f in ("sw_ms", "budget_ms", "hw_ms", "overhead_ms", "feasible", "fill_pct")}
            | {"sw_items": [i for i in st[k]["sw_items"] if i.get("critical") is not False]}
            for k in st
        },
        "ips": ips,
        "warnings": report.get("warnings", []),
    }


def _slice_public(s: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in s.items() if k not in ("warnings", "domains", "ips", "cpu_by_task")} | {
        "stages": {k: {f: v for f, v in st.items() if f != "sw_items"} for k, st in s["stages"].items()}
    }


def _slice_ok(s: dict[str, Any], c: ExplorationConstraints) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    status = s["verdict"]["status"]
    if status == "fail":
        reasons += s["verdict"]["reasons"] or ["timing fail"]
    if status == "clock_up" and not c.allow_clock_up:
        reasons.append("clock above the 25% rule is not allowed")
    if c.require_intervals and not s["intervals_ok"]:
        reasons.append("preview/video interval off target")
    if c.require_power_model and s["power"]["hw_mw"] <= 0:
        reasons.append("IP core power 미모델 (unit_power=0) — power 비교 불가")
    return not reasons, reasons


def _case_ok(case: dict[str, Any], c: ExplorationConstraints) -> bool:
    if case["lossy"] and not c.allow_lossy:
        return False
    if c.power_budget_mw is not None and case["total_mw"] > c.power_budget_mw:
        return False
    return not (c.bw_budget_mbs is not None and case["bw_mbs"] > c.bw_budget_mbs)


# ------------------------------------------------------------------- compression
def _buffer_nodes(graph) -> dict[str, set[str]]:
    nodes: dict[str, set[str]] = {}
    for edge in graph.pipeline_edges:
        b = edge.get("buffer")
        if b and edge_type(edge) == "M2M":
            nodes.setdefault(str(b), set()).update(
                str(x) for x in (edge_source(edge), edge_target(edge)) if x
            )
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    for bid in buffers:
        eff = {**(buffers.get(bid) or {}), **((graph.variant.buffer_overrides or {}).get(bid) or {})}
        for key in ("history", "dma"):
            node = (eff.get(key) or {}).get("node_id")
            if node:
                nodes.setdefault(str(bid), set()).add(str(node))
    return nodes


def _support(graph, nodes: set[str]) -> tuple[str, dict[str, list[str]]]:
    by_id = {str(n.get("id")): n for n in graph.pipeline_nodes}
    listed: dict[str, list[str]] = {}
    unknown = False
    for node in sorted(nodes):
        ip = graph.ip_catalog.get(str((by_id.get(node) or {}).get("ip_ref")))
        caps = getattr(ip, "capabilities", None) or {}
        modes = ((caps.get("supported_features") or {}) if isinstance(caps, dict) else {}).get("compression")
        if not modes:
            unknown = True
            continue
        listed[node] = [str(m) for m in modes]
    if any(not any(compression_enabled(m) and "OFF" not in m.upper() for m in v) for v in listed.values()):
        return "unsupported", listed
    return ("unknown" if unknown else "catalog"), listed


def _dma(graph, config: SimulationRunConfig) -> dict[tuple[str, str, str], tuple[float, float]]:
    inputs = build_simulation_inputs(graph, config)
    fps = float(config.fps or 30.0)
    fps_by_node = {w.node_id: w.fps for w in inputs.workloads}
    model = resolve_power_model(config.power_model)
    out: dict[tuple[str, str, str], tuple[float, float]] = {}
    for t in inputs.port_transfers:
        r = calc_port_bw(t, fps=fps_by_node.get(t.node_id, fps), bw_power_coeff=config.bw_power_coeff,
                         vbat=config.vbat, pmic_efficiency=config.pmic_efficiency, power_model=model)
        key = (t.node_id, t.port, t.port_type.value)
        bw, pw = out.get(key, (0.0, 0.0))
        out[key] = (bw + r.bw_mbs, pw + r.bw_power_mw)
    return out


def compression_candidates(graph, axis: CompressionAxis, config: SimulationRunConfig) -> list[dict[str, Any]]:
    """Per-buffer BW/power delta when that buffer alone is compressed."""
    catalog = compression_catalog(graph.soc)
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    node_map = _buffer_nodes(graph)
    active = {str(n.get("id")) for n in graph.pipeline_nodes}
    base = _dma(graph, config)
    out = []
    for bid, nodes in sorted(node_map.items()):
        if not nodes & active or bid not in buffers:
            continue
        if axis.buffers is not None and bid not in axis.buffers:
            continue
        eff = {**(buffers.get(bid) or {}), **((graph.variant.buffer_overrides or {}).get(bid) or {})}
        fmt = str(eff.get("format") or "")
        fam = "BAYER" if _BAYER_RE.search(fmt) else "YUV"
        support, listed = _support(graph, nodes & active)
        row: dict[str, Any] = {
            "buffer": bid, "format": fmt, "bitdepth": eff.get("bitdepth"), "family": fam,
            "nodes": sorted(nodes & active), "support": support, "listed_modes": listed,
            "base_compression": normalize_compression(eff.get("compression")),
        }
        if compression_enabled(eff.get("compression")):
            out.append(row | {"selectable": False, "skip_reason": "already compressed"})
            continue
        best = None
        for m in axis.modes:
            mode = f"COMP_{fam}_{m.upper()}"
            if mode in axis.ratio_overrides:
                ratio, src = axis.ratio_overrides[mode], "override"
            elif mode in catalog and catalog[mode] < 1.0:
                ratio, src = catalog[mode], "catalog"
            elif m.upper() in DEFAULT_RATIO and mode not in catalog:
                ratio, src = DEFAULT_RATIO[m.upper()], "assumed"
            else:
                continue
            if best is None or ratio < best[1]:
                best = (mode, ratio, src, m == "lossy")
        if best is None:
            out.append(row | {"selectable": False, "skip_reason": "no mode with ratio < 1"})
            continue
        mode, ratio, src, lossy = best
        variant = deepcopy(graph.variant)
        variant.buffer_overrides = deepcopy(variant.buffer_overrides or {})
        variant.buffer_overrides.setdefault(bid, {}).update({"compression": mode, "comp_ratio": ratio})
        comp = _dma(replace(graph, variant=variant), config)
        ports = sorted(k for k in comp if abs(comp[k][0] - base.get(k, (0.0, 0.0))[0]) > 1e-9)
        raw = sum(base.get(k, (0.0, 0.0))[0] for k in ports)
        d_bw = sum(comp[k][0] for k in comp) - sum(v[0] for v in base.values())
        d_pw = sum(comp[k][1] for k in comp) - sum(v[1] for v in base.values())
        row |= {
            "mode": mode, "comp_ratio": ratio, "ratio_source": src, "lossy": lossy,
            "ports": [f"{n}.{p}" for n, p, _ in ports], "raw_mbs": round(raw, 2),
            "delta_mbs": round(d_bw, 3), "delta_mw": round(d_pw, 4),
        }
        reason = None
        if support == "unsupported" and not axis.include_unsupported:
            reason = "IP catalog lists no compression for an endpoint"
        elif -d_bw < axis.min_saving_mbs:
            reason = f"saving {-d_bw:.1f} MB/s < {axis.min_saving_mbs} MB/s"
        out.append(row | {"selectable": reason is None, "skip_reason": reason})
    out.sort(key=lambda r: (not r["selectable"], r.get("delta_mw", 0.0)))
    return out


def _subset_sums(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sets: list[dict[str, Any]] = [{"buffers": (), "delta_mw": 0.0, "delta_mbs": 0.0, "lossy": False, "assumed": False}]
    for b in active:
        sets += [
            {
                "buffers": s["buffers"] + (b["buffer"],),
                "delta_mw": s["delta_mw"] + b["delta_mw"],
                "delta_mbs": s["delta_mbs"] + b["delta_mbs"],
                "lossy": s["lossy"] or b["lossy"],
                "assumed": s["assumed"] or b["ratio_source"] == "assumed",
            }
            for s in sets
        ]
    return sets


# ------------------------------------------------------------------- DVFS
def dvfs_options(ips: list[dict[str, Any]], tables: dict[str, DVFSTable], k: int, asv: int) -> list[dict[str, Any]]:
    """Per domain: resolved level plus up to k faster levels with the HW power delta."""
    doms: dict[str, list[dict[str, Any]]] = {}
    for ip in ips:
        if ip["dvfs_group"] in tables and ip["dvfs_level"] is not None:
            doms.setdefault(ip["dvfs_group"], []).append(ip)
    out = []
    for dom, members in sorted(doms.items()):
        table = tables[dom]
        base_level = min(int(m["dvfs_level"]) for m in members)  # aligned domain; min = fastest
        base = table.get_level(base_level)
        if base is None:
            continue
        faster = sorted(
            (lv for lv in table.levels if lv.speed_mhz > base.speed_mhz and table.voltage_for(lv, asv) > 0),
            key=lambda lv: lv.speed_mhz,
        )[:k]
        opts = []
        for lv in [base, *faster]:
            v = table.voltage_for(lv, asv)
            # resolved level = no change; a faster level only ever raises a member's voltage
            delta = 0.0 if lv is base else sum(
                m["power_mw"] * ((max(v, m["voltage_mv"]) / m["voltage_mv"]) ** 2 - 1.0)
                for m in members if m["voltage_mv"] > 0
            )
            opts.append({"level": lv.level, "speed_mhz": lv.speed_mhz, "voltage_mv": v,
                         "delta_mw": round(delta, 4), "raise": lv.level != base.level})
        out.append({"domain": dom, "base_level": base.level, "nodes": sorted(m["node"] for m in members),
                    "max_required_mhz": round(max(m["required_clock_mhz"] for m in members), 1),
                    "options": opts})
    return out


def _dvfs_sets(domains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not domains:
        return [{"levels": {}, "delta_mw": 0.0, "raises": 0}]
    sets = []
    for combo in product(*[d["options"] for d in domains]):
        sets.append({
            "levels": {d["domain"]: o["level"] for d, o in zip(domains, combo, strict=True)},
            "delta_mw": sum(o["delta_mw"] for o in combo),
            "raises": sum(1 for o in combo if o["raise"]),
        })
    return sets


# ------------------------------------------------------------------- cases
def _case(s: dict[str, Any], cset: dict[str, Any], dset: dict[str, Any]) -> dict[str, Any]:
    p = s["power"]
    hw = p["hw_mw"] + dset["delta_mw"]
    bw = p["bw_mw"] + cset["delta_mw"]
    total = p["cpu_mw"] + hw + bw
    key = "|".join([
        f"s={s['statistic']}", f"x={s['runtime_scale']:g}",
        "c=" + ("+".join(cset["buffers"]) or "-"),
        "d=" + (",".join(f"{k}:L{v}" for k, v in sorted(dset["levels"].items())) or "-"),
    ])
    return {
        "key": key, "statistic": s["statistic"], "runtime_scale": s["runtime_scale"],
        "compression": list(cset["buffers"]), "dvfs": dict(dset["levels"]), "dvfs_raise": dset["raises"],
        "total_mw": total, "cpu_mw": p["cpu_mw"], "hw_mw": hw, "bw_mw": bw,
        "bw_mbs": s["bw"]["total_mbs"] + cset["delta_mbs"],
        "lossy": cset["lossy"], "assumed_ratio": cset["assumed"],
        "verdict": s["verdict"]["status"],
    }


def _rank(cases: list[dict[str, Any]], tie_pct: float) -> list[dict[str, Any]]:
    if not cases:
        return []
    best = min(c["total_mw"] for c in cases)
    tol = best * tie_pct / 100.0

    def key(c: dict[str, Any]) -> tuple:
        tied = c["total_mw"] <= best + tol
        return (not tied, c["total_mw"] if not tied else 0.0, c["bw_mbs"] if tied else 0.0,
                len(c["compression"]), c["dvfs_raise"], c["total_mw"])

    return sorted(cases, key=key)


def _distinct(cases: list[dict[str, Any]], n: int, seen: set[float] | None = None) -> list[dict[str, Any]]:
    """Top-n alternatives with distinct total power (drops zero-cost duplicates, e.g. unmodeled IPs)."""
    seen, out = set(seen or ()), []
    for c in cases:
        sig = round(c["total_mw"], 1)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
        if len(out) >= n:
            break
    return out


def _public_case(c: dict[str, Any] | None) -> dict[str, Any] | None:
    if c is None:
        return None
    out = dict(c)
    for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_mbs"):
        out[k] = round(out[k], 2)
    return out


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    v = sorted(values)

    def q(p: float) -> float:
        pos = p * (len(v) - 1)
        lo = math.floor(pos)
        hi = min(lo + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (pos - lo)

    return {k: round(q(p), 2) for k, p in (("min", 0), ("p25", 0.25), ("median", 0.5), ("p75", 0.75), ("max", 1))}


def _axis_spread(slices, obj_slice, comp_sets, obj) -> dict[str, dict[str, float]]:
    """Total power range when only one axis moves (others at objective/baseline)."""
    def span(vals: list[float]) -> dict[str, float]:
        return {"min": round(min(vals), 2), "max": round(max(vals), 2), "range": round(max(vals) - min(vals), 2)}

    base = obj_slice["power"]["total_mw"]
    stat = [s["power"]["total_mw"] for s in slices if s["runtime_scale"] == obj.runtime_scale]
    scale = [s["power"]["total_mw"] for s in slices if s["statistic"] == obj.statistic]
    comp = [base + c["delta_mw"] for c in comp_sets]
    dv = [base + d["delta_mw"] for d in _dvfs_sets(obj_slice["domains"])]
    return {"sw_statistic": span(stat), "sw_growth": span(scale), "compression": span(comp), "dvfs_headroom": span(dv)}


# ------------------------------------------------------------------- verification
def _verify(graph, spec, config, tables, case, buffers) -> dict[str, Any]:
    by_id = {b["buffer"]: b for b in buffers}
    variant = deepcopy(graph.variant)
    variant.buffer_overrides = deepcopy(variant.buffer_overrides or {})
    for bid in case["compression"]:
        b = by_id[bid]
        variant.buffer_overrides.setdefault(bid, {}).update({"compression": b["mode"], "comp_ratio": b["comp_ratio"]})
    raised = {}
    if case["dvfs_raise"]:
        raised = dict(case["dvfs"])
    cfg = config.model_copy(update={"dvfs_overrides": {**config.dvfs_overrides, **raised}})
    opts = spec.timing.model_copy(update={
        "statistic": case["statistic"], "runtime_scale": case["runtime_scale"],
        "eis": spec.axes.eis, "include_whatif": False,
    })
    r = analyze_timing_budget(replace(graph, variant=variant), opts, config=cfg, dvfs_tables=tables)
    sim_total = float(r["power"]["total_mw"])
    delta = sim_total - case["total_mw"]
    pct = 100.0 * delta / case["total_mw"] if case["total_mw"] else 0.0
    return {
        "method": "re-simulated with buffer_overrides + dvfs_overrides",
        "sim_total_mw": round(sim_total, 2), "analytic_total_mw": round(case["total_mw"], 2),
        "delta_mw": round(delta, 3), "delta_pct": round(pct, 3),
        "sim_bw_mbs": r["bw"]["total_mbs"], "sim_verdict": r["verdict"]["status"],
        "ok": abs(pct) < 0.5 and r["verdict"]["status"] != "fail",
    }


# ------------------------------------------------------------------- SW margin
def sw_margin(slices, obj_slice, obj) -> dict[str, Any]:
    """SW timing margin of SW-gated stages (NRT, Post-NRT) at the objective point.

    margin = (P - SW(runtime+latency) - IP overhead - HW at the set clock) / P
    """
    P = obj_slice["period_ms"]
    rows = []
    for sid in ("nrt", "post"):
        st = obj_slice["stages"].get(sid)
        if not st or (st["sw_ms"] <= 0 and sid == "post"):
            continue
        slack = P - st["sw_ms"] - st["overhead_ms"] - st["hw_ms"]
        items = [i for i in st["sw_items"] if i.get("kind") == "sw"]
        top = max(items, key=lambda i: i["runtime_ms"] + i["latency_ms"], default=None)
        lat = sum(i["latency_ms"] for i in items)
        rows.append({
            "stage": sid, "slack_ms": round(slack, 3), "margin_pct": round(100 * slack / P, 2),
            "sw_ms": st["sw_ms"], "hw_ms": st["hw_ms"], "sw_share_pct": round(100 * st["sw_ms"] / P, 1),
            "latency_share_pct": round(100 * lat / st["sw_ms"], 1) if st["sw_ms"] else 0.0,
            "bottleneck": top["task"] if top else None,
            "bottleneck_ms": round(top["runtime_ms"] + top["latency_ms"], 3) if top else 0.0,
            "bottleneck_share_pct": round(100 * (top["runtime_ms"] + top["latency_ms"]) / st["sw_ms"], 1)
            if top and st["sw_ms"] else 0.0,
        })
    worst = min(rows, key=lambda r: r["margin_pct"], default=None)
    passing = [s["runtime_scale"] for s in slices if s["statistic"] == obj.statistic and s["verdict"]["status"] != "fail"]
    all_scales = sorted(s["runtime_scale"] for s in slices if s["statistic"] == obj.statistic)
    by_stat = {s["statistic"]: s["stages"].get(worst["stage"], {}).get("sw_ms", 0.0)
               for s in slices if worst and s["runtime_scale"] == obj.runtime_scale}
    spread = (max(by_stat.values()) - min(by_stat.values())) if by_stat else 0.0
    out = {
        "definition": "(P - SW - overhead - HW@set clock)/P for NRT and Post-NRT, objective statistic",
        "stages": rows,
        "worst": worst,
        "growth_tolerance": (max(passing) if passing else None),
        "growth_tested_max": (all_scales[-1] if all_scales else None),
        "stat_spread_ms": round(spread, 3),
        "verdict": obj_slice["verdict"]["status"],
    }
    out["recommendations"] = recommendations(out, obj_slice)
    return out


def recommendations(m: dict[str, Any], s: dict[str, Any]) -> list[str]:
    w = m.get("worst")
    if not w:
        return []
    recs = []
    P = s["period_ms"]
    if s["verdict"]["status"] == "fail" or w["margin_pct"] < 0:
        need = max(0.0, -(w["slack_ms"]))
        if w["sw_ms"] >= P:
            need = w["sw_ms"] - 0.5 * P
        recs.append(
            f"spec 미달: {w['stage'].upper()} SW {w['sw_ms']:.1f} ms / period {P:.2f} ms — "
            f"SW 경로 단축 필요 (≥{need:.1f} ms), 병목 {w['bottleneck']} {w['bottleneck_ms']:.1f} ms"
        )
    if w["bottleneck_share_pct"] > 50:
        recs.append(
            f"{w['bottleneck']}가 {w['stage'].upper()} SW의 {w['bottleneck_share_pct']:.0f}% — "
            "task 최적화 / HW offload / big core affinity 검토"
        )
    if w["latency_share_pct"] > 30:
        recs.append(
            f"SW latency(대기)가 SW 경로의 {w['latency_share_pct']:.0f}% — 동기화 지점 축소, "
            "frame N+1 준비 병행(pipelining), queue depth 증가"
        )
    if s["verdict"]["status"] == "clock_up":
        f = s["verdict"].get("nrt_clock_factor")
        recs.append(
            f"25% rule 대비 NRT clock ×{f:.2f} 필요 — SW 단축 시 clock/전압 하향 가능" if f else
            "25% rule 대비 clock 상향 필요"
        )
    if m["stat_spread_ms"] > 0.3 * max(w["sw_ms"], 1e-9):
        recs.append(
            f"SW max–mean 편차 {m['stat_spread_ms']:.1f} ms — 최악 경로 원인 Perfetto profiling, 실측 trace 확보"
        )
    tol, tested = m.get("growth_tolerance"), m.get("growth_tested_max")
    if tol is None:
        recs.append("탐색한 모든 SW 증가율에서 spec 미달")
    elif tested and tol < tested:
        recs.append(f"차기 SW 증가 허용 ×{tol:.1f}까지 (×{tested:.1f}에서 spec 미달)")
    return recs


# ------------------------------------------------------------------- prediction payload
def find_case(summary: dict[str, Any], case_key: str | None) -> tuple[dict[str, Any] | None, str]:
    """Recommended case (auto) or a listed alternative by key (user)."""
    rec = summary.get("recommended")
    if case_key is None or (rec and rec["key"] == case_key):
        return rec, "auto:min-power"
    for rank, alt in enumerate(summary.get("alternatives") or [], start=2):
        if alt["key"] == case_key:
            return alt, f"user:rank-{rank}"
    base = summary.get("baseline")
    if base and base["key"] == case_key:
        return base, "user:baseline"
    return None, ""


def prediction_payload(s: dict[str, Any], case: dict[str, Any], buffers: list[dict[str, Any]]) -> dict[str, Any]:
    """Frozen metrics for a promoted prediction (input to change attribution)."""
    comp = set(case["compression"])
    dom_level = case["dvfs"]
    ips = []
    for ip in s["ips"]:
        ips.append({k: ip[k] for k in ("node", "stage", "dvfs_group", "set_clock_mhz", "dvfs_level",
                                       "voltage_mv", "power_mw", "activity_mw", "cores")})
    # apply DVFS raise to IP rows (analytic: V from domain option)
    if case["dvfs_raise"]:
        for dom in s.get("domains", []):
            lvl = dom_level.get(dom["domain"])
            opt = next((o for o in dom["options"] if o["level"] == lvl), None)
            if not opt or not opt["raise"]:
                continue
            for ip in ips:
                if ip["dvfs_group"] == dom["domain"]:
                    v = max(opt["voltage_mv"], ip["voltage_mv"])
                    ip["set_clock_mhz"], ip["dvfs_level"] = opt["speed_mhz"], opt["level"]
                    ip["power_mw"] = ip["activity_mw"] * (v / V_REF_MV) ** 2
                    ip["voltage_mv"] = v
    bufs = [
        {"buffer": b["buffer"], "raw_mbs": b.get("raw_mbs", 0.0), "compressed": b["buffer"] in comp,
         "mode": b.get("mode") if b["buffer"] in comp else None,
         "comp_ratio": b.get("comp_ratio") if b["buffer"] in comp else 1.0,
         "delta_mbs": b.get("delta_mbs", 0.0) if b["buffer"] in comp else 0.0,
         "delta_mw": b.get("delta_mw", 0.0) if b["buffer"] in comp else 0.0}
        for b in buffers if "raw_mbs" in b
    ]
    return {
        "fps": s["fps"], "period_ms": s["period_ms"], "statistic": case["statistic"],
        "runtime_scale": case["runtime_scale"], "eis_on": s["eis_on"],
        "power": {k: round(case[k], 3) for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw")},
        "bw_mbs": round(case["bw_mbs"], 2), "base_bw_mbs": s["bw"]["total_mbs"], "base_bw_mw": s["power"]["bw_mw"],
        "cpu_by_task": s["cpu_by_task"], "ips": ips, "buffers": bufs,
        "compression": sorted(comp), "dvfs": dom_level, "verdict": s["verdict"]["status"],
        "intervals": s["intervals"], "latency": s["latency"],
        "stages": {k: {f: v for f, v in st.items() if f != "sw_items"} for k, st in s["stages"].items()},
    }


def input_hash(graph, spec, config, tables) -> str:
    payload = {
        "engine": ENGINE_REV,
        "scenario": graph.scenario.id, "variant": graph.variant.id,
        "pipeline": graph.scenario.pipeline, "variant_doc": _variant_doc(graph.variant),
        "spec": spec.model_dump(mode="json"), "config": config.model_dump(mode="json"),
        "dvfs": {k: t.model_dump(mode="json") for k, t in sorted(tables.items())},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _variant_doc(variant) -> Any:
    dump = getattr(variant, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if is_dataclass(variant) and not isinstance(variant, type):
        return asdict(variant)
    return repr(variant)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
