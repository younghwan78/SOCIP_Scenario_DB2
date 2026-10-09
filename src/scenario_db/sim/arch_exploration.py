"""Architecture exploration over a scenario variant.

Axes
- SW timing statistic (min/mean/max) x next-project SW growth scale -> simulated
  (stage timing budget, ``timing_budget.analyze_timing_budget``)
- DVFS headroom: each DVFS domain at its resolved level or up to ``k`` faster
  levels -> analytic (IP power scales with (V/V0)^2, clock only gets faster)
- Buffer compression per M2M/history buffer (OFF or a lossy/lossless mode)
  -> analytic (per-port BW is linear in comp_ratio; the DMA transfer set is
  rebuilt by the real adapter with a ``buffer_overrides`` patch)
- Power options (``sim.power_options``): architecture knob values / substitute IP
  modes that need IQ evaluation. Full factorial of the option dimensions; each
  set is re-simulated at the objective point and gets its own compression/DVFS
  search. Options never become the promoted case of the variant: the result is
  a per-option saving report next to it.

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
from scenario_db.sim.bw_power import bw_model_from_config
from scenario_db.sim.power_model import IP_LEAK_EXPONENT, busy_share, resolve_power_model
from scenario_db.sim.power_model import clock_factor as model_clock_factor
from scenario_db.sim.timing_budget import (
    Statistic,
    TimingBudgetOptions,
    analyze_timing_budget,
)
from scenario_db.sim import power_options as po
from scenario_db.sim.power_attribution import attribute
from scenario_db.sim.transfers import compression_catalog

ENGINE_REV = "arch-exploration/9"  # 9: RT clock = sensor read-out basis, OTF rate align
# Power = CPU(SW) + IP core + BW; BW = IP DMA (HW nodes) + CPU DMA (SW tasks, e.g. mpeg_writer)
DIST_KEYS = ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_ip_mw", "bw_cpu_mw", "bw_mbs", "bw_ip_mbs", "bw_cpu_mbs")
V_REF_MV = 710.0


def _clock_factor(ip: dict[str, Any], set_clock_mhz: float) -> float:
    """v2-vf clock factor (gating aware); 1 under v1 or without a reference clock."""
    return model_clock_factor(float(ip.get("clock_power_fraction") or 0.0), set_clock_mhz,
                              float(ip.get("ref_clock_mhz") or 0.0), ip.get("clock_gating_eff"))


def _ip_power_at(ip: dict[str, Any], voltage_mv: float, set_clock_mhz: float) -> float:
    """IP power at another (V, f): dynamic re-scaled by V^2 x clock factor, leakage by V^k x gating."""
    p = float(ip.get("power_mw") or 0.0)
    v = float(ip.get("voltage_mv") or 0.0)
    f = float(ip.get("set_clock_mhz") or 0.0)
    if v <= 0:
        return p
    leak = float(ip.get("leakage_power_mw") or 0.0)
    dynamic = (p - leak) * (voltage_mv / v) ** 2 * _clock_factor(ip, set_clock_mhz) / _clock_factor(ip, f)
    ref = float(ip.get("ref_clock_mhz") or 0.0)
    pg = float(ip.get("power_gating_eff") or 0.0)
    gate = lambda clock: 1.0 - pg * (1.0 - busy_share(clock, ref))  # noqa: E731
    leak_new = leak * (voltage_mv / v) ** IP_LEAK_EXPONENT * (gate(set_clock_mhz) / gate(f) if gate(f) > 0 else 1.0)
    return dynamic + leak_new


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
    # only DMA whose every endpoint IP declares compression support is explored;
    # False also explores endpoints the catalog says nothing about (support "unknown")
    require_declared: bool = True
    max_buffers: int = Field(default=8, ge=0, le=12)
    min_saving_mbs: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _ratios(self) -> CompressionAxis:
        if any(not (0 < v <= 1) for v in self.ratio_overrides.values()):
            raise ValueError("compression ratio_overrides must be in (0, 1]")
        return self


class PowerOptionAxis(BaseScenarioModel):
    enabled: bool = True
    include_knobs: bool = True
    include_modes: bool = True
    max_sets: int = Field(default=64, ge=1, le=256)  # full factorial above the cap is skipped


class ExplorationAxes(BaseScenarioModel):
    statistics: list[Statistic] = Field(default_factory=_mean_max, min_length=1)
    runtime_scales: list[float] = Field(default_factory=lambda: [1.0, 1.1, 1.2], min_length=1, max_length=8)
    eis: Literal["auto", "on", "off"] = "auto"
    dvfs_headroom_levels: int = Field(default=1, ge=0, le=3)
    compression: CompressionAxis = Field(default_factory=CompressionAxis)
    power_options: PowerOptionAxis = Field(default_factory=PowerOptionAxis)

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
    # A power budget judged on a partial model (some active IPs at 0 mW) is "unknown", not "pass".
    # True: such a variant is not spec OK; False: the budget status is reported as unknown only.
    require_complete_power_for_budget: bool = True


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
    max_cases_per_variant: int = Field(default=200_000, ge=1, le=200_000)
    verify: bool = True
    # model-consistency tolerance (analytic vs re-simulated); NOT a product budget tolerance
    verify_tolerance_pct: float = Field(default=0.5, gt=0, le=10)


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
    summary = _explore(graph, spec, config, tables)
    if spec.axes.power_options.enabled:
        summary["power_options"] = explore_power_options(graph, spec, config, tables, summary)
        summary["counts"]["option_cases"] = summary["power_options"]["cases"]
    summary["input_hash"] = input_hash(graph, spec, config, tables)
    sections, blobs = input_manifest(graph, config, tables)
    summary["input_sections"] = sections  # section -> sha256 of the resolved input (blobs stored per run)
    summary["_manifest_blobs"] = blobs
    return summary


def _explore(graph, spec: ArchExplorationSpec, config: SimulationRunConfig,
             tables: dict[str, DVFSTable]) -> dict[str, Any]:
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

    sw_nodes = set(obj_slice["sw_nodes"]) | {
        str(n.get("id")) for n in graph.pipeline_nodes if str(n.get("role") or "") in ("sw_task", "sw")
    }
    comp_axis = axes.compression
    if not spec.constraints.allow_lossy:
        comp_axis = comp_axis.model_copy(update={"modes": [m for m in comp_axis.modes if m != "lossy"]})
    buffers = compression_candidates(graph, comp_axis, config, sw_nodes) if comp_axis.enabled else []
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
    total_cases = n_comp * sum(math.prod(len(d["options"]) for d in s["domains"]) for s in slices)
    if total_cases > spec.max_cases_per_variant:
        raise ValueError(
            f"exploration exceeds {spec.max_cases_per_variant} cases "
            f"({len(slices)} SW x {n_comp} compression x {n_dvfs} DVFS); reduce axes"
        )

    comp_sets = _subset_sums(active)
    dist: dict[str, list[float]] = {k: [] for k in DIST_KEYS}
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
    alternatives = _distinct(ranked[1:], spec.top_n, seen={_sig(recommended)} if recommended else None)
    pareto = [c for c in _pareto(ranked) if recommended is None or c["key"] != recommended["key"]][: spec.top_n * 2]
    baseline = next(c for c in cases_obj if not c["compression"] and not c["dvfs_raise"])
    ok_obj, obj_reasons = _slice_ok(obj_slice, spec.constraints)
    coverage = _power_coverage(obj_slice)
    budget_status = _power_budget_status(spec.constraints, coverage["power_coverage"], recommended)
    if budget_status == "unknown" and spec.constraints.require_complete_power_for_budget:
        obj_reasons.append(
            "power budget 판정 불가: 활성 IP 전력 미모델 (" + ", ".join(coverage["zero_power_ips"]) + ")"
        )
    if recommended is not None and spec.verify:
        recommended["verified"] = _verify(graph, spec, config, tables, recommended, buffers)
        if not recommended["verified"]["ok"]:
            obj_reasons.append("recommended case failed re-simulation verification: "
                               + "; ".join(recommended["verified"].get("reasons") or ["mismatch"]))
    verified = (recommended or {}).get("verified") or {}

    summary = {
        "engine_rev": ENGINE_REV,
        "scenario_id": graph.scenario.id,
        "variant_id": graph.variant.id,
        "design_conditions": _jsonable(getattr(graph.variant, "design_conditions", None) or {}),
        "severity": getattr(graph.variant, "severity", None),
        "fps": obj_slice["fps"],
        "period_ms": obj_slice["period_ms"],
        "throughput_model": spec.timing.throughput_model,
        "eis_on": obj_slice["eis_on"],
        "mfc_dual": obj_slice["mfc_dual"],
        "spec_ok": recommended is not None and not obj_reasons,
        "spec_reasons": obj_reasons or ([] if recommended is not None else ["no eligible combination"]),
        # decomposed status: spec_ok is the conjunction, these say which part holds
        "status": {
            "timing_feasible": ok_obj,
            "power_coverage": coverage["power_coverage"],
            "power_budget_status": budget_status,
            "model_consistency_verified": (bool(verified.get("power_match") and verified.get("bw_match"))
                                           if verified else None),
            "constraints_verified": verified.get("constraints_pass") if verified else None,
        },
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
        # non-dominated eligible cases (power, BW, IQ risk, DVFS headroom): same power can hide other trade-offs
        "pareto": [{**(_public_case(c) or {}), "iq_risk": _iq_risk(c)} for c in pareto],
        "slices": [_slice_public(s) for s in slices],
        "buffers": buffers,
        "domains": obj_slice["domains"],
        "ip_modes": po.ip_mode_table(graph, obj_slice["ips"]),
        "axis_spread": _axis_spread(slices, obj_slice, comp_sets, obj),
        "sw_margin": sw_margin(slices, obj_slice, obj) | _fixed_growth(slices, obj, recommended),
        # objective slice keeps IP rows + DVFS options: promotion builds the frozen payload from it
        "objective_slice": {k: v for k, v in obj_slice.items() if k != "warnings"},
        "coverage": coverage,
        "warnings": obj_slice["warnings"][:20],
        # IQ/performance-keeping optimum and its near-optimal condition range vs the IQ-trading lossy optimum
        "tiers": _tiers([c for c in cases_obj if c["eligible"]], obj.tie_pct),
    }
    # compact copy for list views (the run table reads it without the whole tiers block)
    keep = (summary["tiers"].get("keep") or {}).get("best")
    summary["keep_total_mw"] = keep["total_mw"] if keep else None
    return summary


TIER_NEAR_PCT = 3.0


def _tiers(eligible: list[dict[str, Any]], tie_pct: float) -> dict[str, Any]:
    """Split the eligible objective-slice cases by what they cost in image quality.

    ``keep`` = no lossy compression and no assumed ratio (iq_risk <= 1): the optimum that keeps IQ and fps,
    plus the *range* of conditions within ``TIER_NEAR_PCT`` of it (DVFS levels per domain, buffers that are
    always / sometimes compressed). These marginal ranges describe tested cases; new combinations need a re-run.
    ``trade`` = the optimum when lossy / assumed-ratio compression is allowed (IQ evaluation needed); its gain vs
    ``keep`` is what giving up IQ buys. Power options (IP mode / knob) are reported separately (``power_options``).
    """
    def window(cases: list[dict[str, Any]]) -> dict[str, Any] | None:
        ranked = _rank(cases, tie_pct)
        if not ranked:
            return None
        best = ranked[0]
        near = [c for c in cases if c["total_mw"] <= best["total_mw"] * (1 + TIER_NEAR_PCT / 100.0)]
        levels: dict[str, list[int]] = {}
        for c in near:
            for d, lv in c["dvfs"].items():
                levels.setdefault(d, []).append(lv)
        comp_count: dict[str, int] = {}
        for c in near:
            for b in c["compression"]:
                comp_count[b] = comp_count.get(b, 0) + 1
        return {
            "best": _public_case(best),
            "near_pct": TIER_NEAR_PCT,
            "near_cases": len(near),
            "near_mw": [round(min(c["total_mw"] for c in near), 2), round(max(c["total_mw"] for c in near), 2)],
            "near_bw_mbs": [round(min(c["bw_mbs"] for c in near)), round(max(c["bw_mbs"] for c in near))],
            "dvfs_range": {d: [min(v), max(v)] for d, v in sorted(levels.items())},
            "compression_always": sorted(b for b, n in comp_count.items() if n == len(near)),
            "compression_optional": sorted(b for b, n in comp_count.items() if n < len(near)),
            # the window is this set of evaluated cases — axis min/max crossed freely is NOT evaluated
            "near_list": [{k: c[k] for k in ("key", "dvfs", "compression", "statistic", "runtime_scale")}
                          | {"total_mw": round(c["total_mw"], 2), "bw_mbs": round(c["bw_mbs"], 1)}
                          for c in sorted(near, key=lambda c: c["total_mw"])[:12]],
        }

    keep = window([c for c in eligible if _iq_risk(c) <= 1])
    trade = window(eligible)
    gain = None
    if keep and trade:
        gain = {"delta_mw": round(trade["best"]["total_mw"] - keep["best"]["total_mw"], 2),
                "delta_mbs": round(trade["best"]["bw_mbs"] - keep["best"]["bw_mbs"], 1),
                "iq_risk": _iq_risk(trade["best"])}
    return {"keep": keep, "trade": trade, "trade_gain": gain}


def option_marginals(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Effect of adding one option to every set that lacks it (conditional on the other options).

    An option whose effect is negative in every context (e.g. L0 bypass) is ``always_beneficial``: it wins in every
    combination, so ranking whole sets hides the rest. The UI fixes such options and ranks the others on
    ``effect_given_fixed`` instead (= set delta minus the delta of the fixed options alone).
    """
    def metric(r: dict[str, Any]) -> float | None:
        v = r.get("delta_mw")
        return float(v) if v is not None else (float(r["raw_delta_mw"]) if r.get("raw_delta_mw") is not None else None)

    by_set = {frozenset(r["items"]): r for r in results}
    label = {k: lb for r in results for k, lb in zip(r["items"], r["labels"], strict=False)}
    effects: dict[str, list[float]] = {}
    for r in results:
        m = metric(r)
        if m is None:
            continue
        items = frozenset(r["items"])
        for it in items:
            rest = items - {it}
            if rest:
                parent = by_set.get(rest)
                pm = metric(parent) if parent is not None else None
                if pm is None:
                    continue
            else:
                pm = 0.0
            effects.setdefault(it, []).append(m - pm)
    out = []
    for it, v in effects.items():
        out.append({
            "key": it, "label": label.get(it, it), "contexts": len(v),
            "mean_mw": round(sum(v) / len(v), 2), "min_mw": round(min(v), 2), "max_mw": round(max(v), 2),
            "always_beneficial": max(v) < 0, "sign_varies": min(v) < 0 < max(v),
        })
    out.sort(key=lambda x: x["mean_mw"])
    # one value per dimension ("knob:name" / "mode:node"): the strongest always-beneficial value
    per_dim: dict[str, str] = {}
    for x in out:
        dim = x["key"].split("=", 1)[0]
        x["dimension"] = dim
        if x["always_beneficial"] and dim not in per_dim:
            per_dim[dim] = x["key"]
    for x in out:
        x["fixed"] = x["key"] in per_dim.values()
    fixed = frozenset(per_dim.values())
    base = by_set.get(fixed)
    base_m = metric(base) if base is not None else None
    for r in results:
        m = metric(r)
        r["effect_given_fixed"] = (round(m - base_m, 2) if m is not None and base_m is not None
                                   and fixed and fixed <= frozenset(r["items"]) and frozenset(r["items"]) != fixed else None)
    return out


def _power_coverage(obj_slice: dict[str, Any]) -> dict[str, Any]:
    zero = list(obj_slice["zero_power_ips"])
    hw = obj_slice["power"]["hw_mw"] > 0
    level = "none" if not hw else "partial" if zero else "complete"
    return {
        "zero_power_ips": zero,
        "hw_power_modeled": hw,
        "cpu_power_modeled": obj_slice["power"]["cpu_mw"] > 0,
        "power_coverage": level,
        # totals are sums over modeled IPs only unless coverage is complete
        "power_total_basis": "complete" if level == "complete" else "modeled_ips_only",
    }


def _power_budget_status(c: ExplorationConstraints, coverage: str, recommended: dict[str, Any] | None) -> str:
    if c.power_budget_mw is None:
        return "n/a"
    if recommended is None:
        return "fail"
    return "pass" if coverage == "complete" else "unknown"


# ------------------------------------------------------------------- power options
def explore_power_options(graph, spec: ArchExplorationSpec, config: SimulationRunConfig,
                          tables: dict[str, DVFSTable], base: dict[str, Any]) -> dict[str, Any]:
    """Predicted saving of every power-option set relative to the variant itself.

    Reference = the variant's recommended case (same objective, own compression/DVFS
    search per set); ``raw_delta_mw`` compares the no-compression / resolved-DVFS
    baselines, so it isolates the option itself.
    """
    axis = spec.axes.power_options
    dims, notes = po.option_dimensions(graph, include_knobs=axis.include_knobs, include_modes=axis.include_modes)
    out: dict[str, Any] = {
        "status": "ok", "dimensions": [{k: v for k, v in d.items()} for d in dims], "notes": notes,
        "sets": po.count_sets(dims), "max_sets": axis.max_sets, "cases": 0,
        "results": [], "best": None, "errors": [],
    }
    if not dims:
        out["status"] = "none"
        return out
    if out["sets"] > axis.max_sets:
        out["status"] = "skipped"
        out["notes"].append(f"{out['sets']} option sets > max_sets {axis.max_sets}; narrow the options")
        return out
    obj = spec.objective
    sub = spec.model_copy(update={
        "axes": spec.axes.model_copy(update={
            "statistics": [obj.statistic], "runtime_scales": [obj.runtime_scale],
            "power_options": axis.model_copy(update={"enabled": False}),
        }),
        "verify": False, "top_n": 1,
    })
    base_raw = base["baseline"]
    remaining = spec.max_cases_per_variant - base.get("counts", {}).get("cases", 0)
    for items in po.option_sets(dims):
        key = po.set_key(items)
        if remaining <= 0:
            out["notes"].append("case budget exhausted; remaining power-option sets were skipped")
            break
        try:
            bounded = sub.model_copy(update={"max_cases_per_variant": remaining})
            r = _explore(po.apply_option_set(graph, items), bounded, config, tables)
        except (LookupError, ValueError, po.KnobError) as exc:
            out["errors"].append({"key": key, "error": str(exc)[:300]})
            continue
        evaluated = r.get("counts", {}).get("cases", 0)
        out["cases"] += evaluated
        remaining -= evaluated
        comparable = bool(base.get("recommended") and r.get("recommended"))
        ref_case = base["recommended"] if comparable else base_raw
        ref_payload = prediction_payload(base["objective_slice"], ref_case, base["buffers"])
        case = r["recommended"] if comparable else r["baseline"]
        payload = prediction_payload(r["objective_slice"], case, r["buffers"])
        att = attribute(ref_payload, payload)
        rec = r.get("recommended")
        delta = rec["total_mw"] - base["recommended"]["total_mw"] if rec and base.get("recommended") else None
        raw = r["baseline"]["total_mw"] - base_raw["total_mw"]
        out["results"].append({
            "key": key,
            "items": [i["key"] for i in items],
            "labels": [i["label"] for i in items],
            "kinds": sorted({i["kind"] for i in items}),
            "iq_eval": "required" if any(i.get("iq_eval", "required") == "required" for i in items) else "not_required",
            "spec_ok": r["spec_ok"], "spec_reasons": r["spec_reasons"],
            "verdict": r["objective_slice"]["verdict"]["status"],
            "case_key": rec["key"] if rec else None,
            "total_mw": round(rec["total_mw"], 3) if rec else None,
            "delta_mw": round(delta, 3) if delta is not None else None,
            "delta_pct": round(100 * delta / base["recommended"]["total_mw"], 2)
            if delta is not None and base["recommended"]["total_mw"] else None,
            "bw_mbs": round(rec["bw_mbs"], 2) if rec else None,
            "delta_bw_mbs": round(rec["bw_mbs"] - base["recommended"]["bw_mbs"], 2)
            if rec and base.get("recommended") else None,
            "raw_total_mw": round(r["baseline"]["total_mw"], 3),
            "raw_delta_mw": round(raw, 3),
            "raw_delta_pct": round(100 * raw / base_raw["total_mw"], 2) if base_raw["total_mw"] else None,
            "attribution": {
                "reference": "recommended" if comparable else "baseline",
                "delta_mw": att["delta_mw"], "components": att["components"],
                "by_category": att["by_category"], "factors": att["factors"][:8],
            },
            "compression": rec["compression"] if rec else [],
            "dvfs": rec["dvfs"] if rec else {},
            "fill_pct": {k: v["fill_pct"] for k, v in r["objective_slice"]["stages"].items()},
            # PPA: latency at the objective slice (before compression/DVFS raise) vs the base variant
            "latency": r["objective_slice"].get("latency"),
            "delta_latency_ms": _latency_delta(base["objective_slice"].get("latency"), r["objective_slice"].get("latency")),
            "zero_power_ips": r["objective_slice"]["zero_power_ips"],
        })
    def rank(x: dict[str, Any]) -> tuple:
        d = x["delta_mw"] if x["delta_mw"] is not None else x["raw_delta_mw"]
        return (not x["spec_ok"], d, len(x["items"]))
    out["results"].sort(key=rank)
    out["marginal"] = option_marginals(out["results"])
    out["fixed"] = [m["key"] for m in out["marginal"] if m["fixed"]]
    best = next((x for x in out["results"] if x["spec_ok"] and (x["delta_mw"] or 0) < 0), None)
    out["best"] = best["key"] if best else None
    return out


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
            "clock_power_fraction": float(ip.get("clock_power_fraction") or 0.0),
            "ref_clock_mhz": float(ip.get("ref_clock_mhz") or 0.0),
            "clock_gating_eff": ip.get("clock_gating_eff"),
            "power_gating_eff": ip.get("power_gating_eff"),
            "leakage_power_mw": float(ip.get("leakage_power_mw") or 0.0),
            # IP power = activity x (V/710)^2 x clock factor (1 under v1-vfps) -> attribution factor
            "activity_mw": p / (v / V_REF_MV) ** 2 / _clock_factor(ip, float(ip["set_clock_mhz"] or 0.0))
            if v > 0 else p,
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
        "cpu_basis": (report["power"].get("cpu_profile") or {}).get("kind", "flat"),
        "zero_power_ips": report["power"].get("zero_power_ips", []),
        "bw": {k: report["bw"][k] for k in ("total_mbs", "hw_mbs", "sw_mbs")},
        "sw_nodes": sorted(report["bw"].get("sw_by_task", {})),
        "stages": {
            k: {f: st[k][f] for f in ("sw_ms", "budget_ms", "hw_ms", "overhead_ms", "feasible", "fill_pct")}
            | {f: st[k][f] for f in ("throughput", "longest_sw_ms", "chain_ms") if f in st[k]}
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


def _case_reasons(case: dict[str, Any], c: ExplorationConstraints) -> list[str]:
    reasons: list[str] = []
    if case["lossy"] and not c.allow_lossy:
        reasons.append("lossy compression not allowed")
    if c.power_budget_mw is not None and case["total_mw"] > c.power_budget_mw:
        reasons.append(f"power {case['total_mw']:.1f} mW > budget {c.power_budget_mw:g} mW")
    if c.bw_budget_mbs is not None and case["bw_mbs"] > c.bw_budget_mbs:
        reasons.append(f"BW {case['bw_mbs']:.1f} MB/s > budget {c.bw_budget_mbs:g} MB/s")
    return reasons


def _case_ok(case: dict[str, Any], c: ExplorationConstraints) -> bool:
    return not _case_reasons(case, c)


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


def _port_unsupported(graph, ports: list[tuple[str, str, str]], mode: str) -> list[str]:
    """DMA ports whose IP module declares ``supported_compressions`` without ``mode``.

    IP catalog ``capabilities.properties.modules[name=<port>].supported_compressions`` is per
    DMA port; ports without that list (or without a module entry) are not restricted.
    """
    want = normalize_compression(mode)
    by_id = {str(n.get("id")): n for n in graph.pipeline_nodes}
    out = []
    for node, port, _ in ports:
        ip = graph.ip_catalog.get(str((by_id.get(node) or {}).get("ip_ref")))
        caps = getattr(ip, "capabilities", None) or {}
        modules = ((caps.get("properties") or {}).get("modules") or []) if isinstance(caps, dict) else []
        mod = next((m for m in modules if isinstance(m, dict) and m.get("name") == port), None)
        listed = (mod or {}).get("supported_compressions")
        if listed is None:
            continue
        if want not in {normalize_compression(v) for v in listed}:
            out.append(f"{node}.{port}")
    return out


def _dma(graph, config: SimulationRunConfig) -> dict[tuple[str, str, str], tuple[float, float]]:
    inputs = build_simulation_inputs(graph, config)
    fps = float(inputs.config.fps or 30.0)
    fps_by_node = {w.node_id: w.fps for w in inputs.workloads}
    model = resolve_power_model(config.power_model)
    bw_model = bw_model_from_config(config)
    out: dict[tuple[str, str, str], tuple[float, float]] = {}
    for t in inputs.port_transfers:
        r = calc_port_bw(t, fps=fps_by_node.get(t.node_id, fps), bw_power_coeff=config.bw_power_coeff,
                         vbat=config.vbat, pmic_efficiency=config.pmic_efficiency, power_model=model,
                         bw_model=bw_model)
        key = (t.node_id, t.port, t.port_type.value)
        bw, pw = out.get(key, (0.0, 0.0))
        out[key] = (bw + r.bw_mbs, pw + r.bw_power_mw)
    return out


def compression_candidates(
    graph, axis: CompressionAxis, config: SimulationRunConfig, sw_nodes: set[str] | None = None
) -> list[dict[str, Any]]:
    """Per-buffer BW/power delta when that buffer alone is compressed (split IP DMA / CPU DMA)."""
    sw = sw_nodes or set()
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
        cands = []
        for m in axis.modes:
            mode = f"COMP_{fam}_{m.upper()}"
            if not axis.include_unsupported and any(
                mode not in {normalize_compression(v) for v in modes}
                and f"COMP_{m.upper()}" not in {str(v).upper() for v in modes}
                for modes in listed.values()
            ):
                continue
            if mode in axis.ratio_overrides:
                ratio, src = axis.ratio_overrides[mode], "override"
            elif mode in catalog and catalog[mode] < 1.0:
                ratio, src = catalog[mode], "catalog"
            elif m.upper() in DEFAULT_RATIO and mode not in catalog:
                ratio, src = DEFAULT_RATIO[m.upper()], "assumed"
            else:
                continue
            cands.append((mode, ratio, src, m == "lossy"))
        if not cands:
            out.append(row | {"selectable": False, "skip_reason": "no mode with ratio < 1"})
            continue
        cands.sort(key=lambda c: c[1])
        chosen = None
        port_block: list[str] = []
        for cand in cands:
            variant = deepcopy(graph.variant)
            variant.buffer_overrides = deepcopy(variant.buffer_overrides or {})
            variant.buffer_overrides.setdefault(bid, {}).update({"compression": cand[0], "comp_ratio": cand[1]})
            comp = _dma(replace(graph, variant=variant), config)
            ports = sorted(k for k in comp if abs(comp[k][0] - base.get(k, (0.0, 0.0))[0]) > 1e-9)
            blocked = _port_unsupported(graph, ports, cand[0])
            if chosen is None or (not blocked and port_block):
                chosen, port_block = (cand, comp, ports), blocked
            if not blocked:
                break
        assert chosen is not None  # cands is nonempty; the first candidate is always retained
        (mode, ratio, src, lossy), comp, ports = chosen
        raw = sum(base.get(k, (0.0, 0.0))[0] for k in ports)
        d_bw = sum(comp[k][0] for k in comp) - sum(v[0] for v in base.values())
        d_pw = sum(comp[k][1] for k in comp) - sum(v[1] for v in base.values())
        keys = set(comp) | set(base)

        def _part(cpu: bool, i: int) -> float:
            return sum(comp.get(k, (0.0, 0.0))[i] - base.get(k, (0.0, 0.0))[i] for k in keys if (k[0] in sw) == cpu)
        row |= {
            "mode": mode, "comp_ratio": ratio, "ratio_source": src, "lossy": lossy,
            "ports": [f"{n}.{p}" for n, p, _ in ports], "raw_mbs": round(raw, 2),
            "delta_mbs": round(d_bw, 3), "delta_mw": round(d_pw, 4),
            "delta_ip_mbs": round(_part(False, 0), 3), "delta_ip_mw": round(_part(False, 1), 4),
            "delta_cpu_mbs": round(_part(True, 0), 3), "delta_cpu_mw": round(_part(True, 1), 4),
            "unsupported_ports": port_block,
        }
        reason = None
        undeclared = [n for n in row["nodes"] if n not in listed]
        if support == "unsupported" and not axis.include_unsupported:
            reason = "IP catalog lists no compression for an endpoint"
        elif undeclared and axis.require_declared and not axis.include_unsupported:
            reason = f"compression support not declared: {', '.join(undeclared)}"
        elif port_block and not axis.include_unsupported:
            reason = f"DMA port without {mode}: {', '.join(port_block)}"
        elif -d_bw < axis.min_saving_mbs:
            reason = f"saving {-d_bw:.1f} MB/s < {axis.min_saving_mbs} MB/s"
        out.append(row | {"selectable": reason is None, "skip_reason": reason})
    out.sort(key=lambda r: (not r["selectable"], r.get("delta_mw", 0.0)))
    return out


_DELTA_KEYS = ("delta_mw", "delta_mbs", "delta_ip_mw", "delta_ip_mbs", "delta_cpu_mw", "delta_cpu_mbs")


def _subset_sums(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zero = {k: 0.0 for k in _DELTA_KEYS}
    sets: list[dict[str, Any]] = [{"buffers": (), **zero, "lossy": False, "assumed": False}]
    for b in active:
        sets += [
            {
                "buffers": s["buffers"] + (b["buffer"],),
                **{k: s[k] + b.get(k, 0.0) for k in _DELTA_KEYS},
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
                _ip_power_at(m, max(v, m["voltage_mv"]), lv.speed_mhz) - m["power_mw"]
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
    p, b = s["power"], s["bw"]
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
        "bw_mbs": b["total_mbs"] + cset["delta_mbs"],
        "bw_ip_mw": p["bw_hw_mw"] + cset["delta_ip_mw"], "bw_cpu_mw": p["bw_sw_mw"] + cset["delta_cpu_mw"],
        "bw_ip_mbs": b["hw_mbs"] + cset["delta_ip_mbs"], "bw_cpu_mbs": b["sw_mbs"] + cset["delta_cpu_mbs"],
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


def _sig(c: dict[str, Any]) -> tuple:
    """Alternative identity: equal power with a different BW or IQ risk is a different trade-off."""
    return (round(c["total_mw"], 1), round(c["bw_mbs"]), bool(c["lossy"]), bool(c["assumed_ratio"]))


def _iq_risk(c: dict[str, Any]) -> int:
    """0 = no compression, 1 = lossless catalog ratio, 2 = assumed ratio, 3 = lossy (IQ evaluation needed)."""
    if not c["compression"]:
        return 0
    return 3 if c["lossy"] else 2 if c["assumed_ratio"] else 1


def _pareto(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Non-dominated cases on (power, BW, IQ risk, -DVFS raise), returned in power order.

    Sweep power in ascending order and query prefix-minimum BW by IQ risk and
    descending DVFS raise. This stays O(n log n) even when every case survives.
    """
    raises = {value: i for i, value in enumerate(sorted({c["dvfs_raise"] for c in cases}, reverse=True), 1)}
    trees = [[math.inf] * (len(raises) + 1) for _ in range(4)]
    ordered = sorted((c["total_mw"], c["bw_mbs"], _iq_risk(c), -c["dvfs_raise"], i, c)
                     for i, c in enumerate(cases))
    out = []
    for _, bw, risk, neg_raise, _, case in ordered:
        index = raises[-neg_raise]
        best_bw = math.inf
        for tree in trees[:risk + 1]:
            j = index
            while j:
                best_bw = min(best_bw, tree[j])
                j -= j & -j
        if best_bw <= bw + 1e-9:
            continue  # dominated, or the same four-axis point already represented
        out.append(case)
        j = index
        while j < len(trees[risk]):
            trees[risk][j] = min(trees[risk][j], bw)
            j += j & -j
    return out


def _fixed_growth(slices: list[dict[str, Any]], obj: Any, rec: dict[str, Any] | None) -> dict[str, Any]:
    """SW growth the *recommended* DVFS levels absorb (no re-selection), vs the re-optimised tolerance.

    A growth slice passes when its timing verdict is not fail and, per DVFS domain, the recommended
    level's speed covers that slice's required clock (analytic check; no extra simulation).
    """
    if rec is None:
        return {"growth_tolerance_fixed": None}
    speed: dict[str, dict[int, float]] = {}
    for s in slices:
        for d in s.get("domains") or []:
            for o in d["options"]:
                speed.setdefault(d["domain"], {})[o["level"]] = o["speed_mhz"]
    rows = []
    for s in sorted((x for x in slices if x["statistic"] == obj.statistic), key=lambda x: x["runtime_scale"]):
        short = [d["domain"] for d in s.get("domains") or []
                 if speed.get(d["domain"], {}).get(rec["dvfs"].get(d["domain"], d["base_level"]), 0.0) < d["max_required_mhz"]]
        rows.append({"runtime_scale": s["runtime_scale"], "ok": s["verdict"]["status"] != "fail" and not short,
                     "short_domains": short})
    tol = None
    for r in rows:
        if r["runtime_scale"] < obj.runtime_scale:
            continue
        if not r["ok"]:
            break
        tol = r["runtime_scale"]
    return {"growth_tolerance_fixed": tol, "growth_fixed_rows": rows,
            "growth_tolerance_basis": {"growth_tolerance": "DVFS re-selected per growth (re-optimisable range)",
                                       "growth_tolerance_fixed": "recommended DVFS levels held (robustness)"}}


def _distinct(cases: list[dict[str, Any]], n: int, seen: set[tuple] | None = None) -> list[dict[str, Any]]:
    """Top-n alternatives with a distinct (power, BW, IQ risk) signature (drops zero-cost duplicates)."""
    seen, out = set(seen or ()), []
    for c in cases:
        sig = _sig(c)
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
    for k in DIST_KEYS:
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
    """Re-simulate a case and re-apply the product constraints to the re-simulated numbers.

    Two tolerances are kept apart: ``verify_tolerance_pct`` is model consistency (analytic vs
    re-simulated), the budgets in ``constraints`` are product limits and get no tolerance.
    """
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
    tol = spec.verify_tolerance_pct
    sim_total = float(r["power"]["total_mw"])
    sim_bw = float(r["bw"]["total_mbs"])
    delta = sim_total - case["total_mw"]
    pct = 100.0 * delta / case["total_mw"] if case["total_mw"] else (0.0 if not sim_total else None)
    bw_delta = sim_bw - case["bw_mbs"]
    bw_pct = 100.0 * bw_delta / case["bw_mbs"] if case["bw_mbs"] else (0.0 if not sim_bw else None)
    power_match = pct is not None and abs(pct) < tol
    bw_match = bw_pct is not None and abs(bw_pct) < tol
    sim_slice = _slice(r, case["statistic"], case["runtime_scale"])
    timing_pass, reasons = _slice_ok(sim_slice, spec.constraints)
    sim_case = {"lossy": case["lossy"], "total_mw": sim_total, "bw_mbs": sim_bw}
    budget_reasons = _case_reasons(sim_case, spec.constraints)
    constraints_pass = timing_pass and not budget_reasons
    if not power_match:
        difference = f"{pct:+.2f}%" if pct is not None else "nonzero simulation against zero estimate"
        reasons.append(f"power model mismatch {difference} (tolerance {tol}%)")
    if not bw_match:
        difference = f"{bw_pct:+.2f}%" if bw_pct is not None else "nonzero simulation against zero estimate"
        reasons.append(f"BW model mismatch {difference} (tolerance {tol}%)")
    reasons += budget_reasons
    return {
        "method": "re-simulated with buffer_overrides + dvfs_overrides; constraints re-applied",
        "tolerance_pct": tol,
        "sim_total_mw": round(sim_total, 2), "analytic_total_mw": round(case["total_mw"], 2),
        "delta_mw": round(delta, 3), "delta_pct": round(pct, 3) if pct is not None else None,
        "sim_bw_mbs": round(sim_bw, 2), "analytic_bw_mbs": round(case["bw_mbs"], 2),
        "bw_delta_mbs": round(bw_delta, 3), "bw_delta_pct": round(bw_pct, 3) if bw_pct is not None else None,
        "sim_verdict": r["verdict"]["status"],
        "power_match": power_match, "bw_match": bw_match,
        "timing_pass": timing_pass, "constraints_pass": constraints_pass,
        "reasons": reasons,
        "ok": power_match and bw_match and constraints_pass,
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
        # sw_ms already includes the serialized per-IP overhead.
        slack = P - st["sw_ms"] - st["hw_ms"]
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
        "definition": "(P - SW including overhead - HW@set clock)/P for NRT and Post-NRT, objective statistic",
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
    for rank, candidate in enumerate(summary.get("pareto") or [], start=1):
        if candidate["key"] == case_key:
            return candidate, f"user:pareto-{rank}"
    base = summary.get("baseline")
    if base and base["key"] == case_key:
        return base, "user:baseline"
    return None, ""


def _latency_delta(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in ("preview_ms", "video_ms"):
        a, b = (old or {}).get(k), (new or {}).get(k)
        out[k] = round(b - a, 3) if a is not None and b is not None else None
    return out


def prediction_payload(s: dict[str, Any], case: dict[str, Any], buffers: list[dict[str, Any]]) -> dict[str, Any]:
    """Frozen metrics for a promoted prediction (input to change attribution)."""
    comp = set(case["compression"])
    dom_level = case["dvfs"]
    ips = []
    for ip in s["ips"]:
        ips.append({k: ip.get(k) for k in ("node", "stage", "dvfs_group", "set_clock_mhz", "dvfs_level",
                                           "voltage_mv", "power_mw", "activity_mw", "cores",
                                           "clock_power_fraction", "ref_clock_mhz", "clock_gating_eff",
                                           "power_gating_eff", "leakage_power_mw")})
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
                    ip["power_mw"] = _ip_power_at(ip, v, opt["speed_mhz"])
                    ip["dvfs_level"] = opt["level"]
                    ip["set_clock_mhz"], ip["voltage_mv"] = opt["speed_mhz"], v
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
        "power": {k: round(case[k], 3) for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_ip_mw", "bw_cpu_mw")},
        "bw_mbs": round(case["bw_mbs"], 2), "bw_ip_mbs": round(case["bw_ip_mbs"], 2), "bw_cpu_mbs": round(case["bw_cpu_mbs"], 2),
        "base_bw_mbs": s["bw"]["total_mbs"], "base_bw_mw": s["power"]["bw_mw"],
        "base_bw_ip_mw": s["power"]["bw_hw_mw"], "base_bw_cpu_mw": s["power"]["bw_sw_mw"],
        "base_bw_ip_mbs": s["bw"]["hw_mbs"], "base_bw_cpu_mbs": s["bw"]["sw_mbs"],
        "cpu_by_task": s["cpu_by_task"], "ips": ips, "buffers": bufs,
        "compression": sorted(comp), "dvfs": dom_level, "verdict": s["verdict"]["status"],
        # why: reasons + NRT clock factor of the objective slice (board / 판정 popover)
        "verdict_detail": {k: s["verdict"].get(k) for k in ("status", "reasons", "nrt_clock_factor")},
        "intervals_ok": s.get("intervals_ok"),
        "lossy": case["lossy"], "assumed_ratio": case["assumed_ratio"],
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
        "simulation_inputs": build_simulation_inputs(graph, config).model_dump(mode="json"),
        "ip_capabilities": {key: row.capabilities for key, row in sorted(graph.ip_catalog.items())},
        "power_options": getattr(graph.scenario, "power_options", None),
        "soc_catalog": getattr(graph.soc, "compression_modes", None),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def input_manifest(graph, config, tables) -> tuple[dict[str, str], dict[str, Any]]:
    """Resolved inputs of one variant as content-addressed sections.

    ``input_hash`` proves *whether* inputs changed; this keeps *what* they were (config, DVFS tables,
    pipeline, variant, IP capabilities, power options) so a past run can be re-created after the
    catalog moved on. Blobs are deduplicated by sha256 at run level.
    """
    raw: dict[str, Any] = {
        "pipeline": _jsonable(graph.scenario.pipeline), "variant_doc": _jsonable(_variant_doc(graph.variant)),
        "config": config.model_dump(mode="json"),
        "simulation_inputs": build_simulation_inputs(graph, config).model_dump(mode="json"),
        "power_options": _jsonable(getattr(graph.scenario, "power_options", None)),
        "soc_catalog": _jsonable(getattr(graph.soc, "compression_modes", None)),
    }
    raw |= {f"dvfs:{k}": t.model_dump(mode="json") for k, t in sorted(tables.items())}
    raw |= {f"ip:{k}": _jsonable(row.capabilities) for k, row in sorted(graph.ip_catalog.items())}
    sections, blobs = {}, {}
    for name, value in raw.items():
        digest = _sha(value)
        sections[name] = digest
        blobs[digest] = value
    return sections, blobs


def _variant_doc(variant) -> Any:
    dump = getattr(variant, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if is_dataclass(variant) and not isinstance(variant, type):
        return asdict(variant)
    return repr(variant)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
