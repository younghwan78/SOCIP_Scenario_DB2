"""Subsystem evaluator ``mcps-v1`` (R-4 / M-4): load, clock and power inside one node (ABOX first).

For a node that declares ``subsystem`` (scenario node, patched by the variant's
``node_configs.<node>.sim.subsystem``; see models/definition/subsystem.py):

* **active** stages / routes / wake sources are the ones whose ``when`` / ``when_node_enabled`` match the variant
  (the knob selector rule).
* **load** of a cpu / dsp unit = sum over its active stages of ``mcps`` (or ``mcycles_per_period`` x 1000 /
  period_ms of the stage stream), in MHz-equivalent Mcycle/s.
* **clock** of a clock domain = the lowest operating point (unit ``freqs_mhz``, else the node IP catalog DVFS
  levels, e.g. ABOX ``aud_qos_levels_khz``) at which every unit of the domain stays at or below its
  ``target_util``; the top point otherwise (infeasible when a unit is above 1).
* **power**: cpu / dsp units by util-vf-v1 (the domain-load model) at the domain clock; hw / memory / interface
  units by their constant ``mw``; a unit without power is listed as unattributed (not counted as 0).
* **deadline slack** per stream = min over the units its stages run on of period x (1 - util).
* **route latency** (exactly one active route when routes are declared) = for each stream along the route its
  buffering (period x periods) + each stage's work per period at the domain clock.
* **wake** rates (wakeups/s per source) are reported for the residency evaluator (M-5); not costed here.

The node's power is the subsystem total, in place of its ``domain_load``; stages ``bind`` to other nodes only
to show where their load belongs (never added there).
"""

from __future__ import annotations

import math
from typing import Any

from scenario_db.authoring.knobs import _match
from scenario_db.authoring.patch import deep_merge
from scenario_db.models.definition.subsystem import COMPUTE_KINDS, SubsystemSpec
from scenario_db.sim.domain_loads import DomainPowerModel, _catalog_defaults

GATED_KINDS = frozenset({"hw", "interface"})   # off without an active stage; memory stays on

MODEL_ID = "mcps-v1"


def subsystem_config(node: dict[str, Any] | None, node_config: dict[str, Any]) -> dict[str, Any] | None:
    """The merged declaration of one node (scenario node, then the variant patch), or None when it has none.
    ``sim.subsystem: none`` in the variant turns a scenario subsystem off (the node keeps its domain load)."""
    sim = node_config.get("sim") or {}
    own = sim.get("subsystem")
    base = (node or {}).get("subsystem")
    nid = (node or {}).get("id")
    if isinstance(own, str):
        if own.lower() == "none":
            return None
        raise ValueError(f"{nid}: sim.subsystem takes a patch mapping or 'none', not {own!r}")
    if own is not None and not isinstance(own, dict):
        raise ValueError(f"{nid}: sim.subsystem takes a patch mapping or 'none', not {type(own).__name__}")
    if base is not None and not isinstance(base, dict):
        raise ValueError(f"{nid}: subsystem must be a mapping")
    if own is None and base is None:
        return None
    if own is None:
        return base
    try:
        return deep_merge(base or {}, own)
    except (AttributeError, TypeError) as exc:     # a malformed $items / $unset / ... operation
        raise ValueError(f"{nid}: sim.subsystem patch is malformed ({exc})") from None


def _given(d: dict[str, Any], key: str, default: float) -> float:
    """``d[key]`` when it is set (an explicit 0 included), else ``default``."""
    v = d.get(key)
    return default if v is None else float(v)


def _unit_power(node_id: str, u, load: float, f: float) -> dict[str, float]:
    """util-vf-v1 of one cpu / dsp unit at clock ``f``: busy x C f V^2 + leakage (gated when idle)."""
    p = u.power or {}
    leak = p.get("leakage") or {}
    vf = sorted((float(r["mhz"]), float(r["mv"])) for r in p["vf"])
    model = DomainPowerModel(name=f"{node_id}.{u.id}", ip_ref="", coeff_uw_per_mhz_v2=float(p["coeff_uw_per_mhz_v2"]),
                             vf=tuple(vf), leak_mw_at_ref=_given(leak, "mw_at_ref", 0.0),
                             leak_ref_mv=_given(leak, "ref_mv", 750.0), leak_exponent=_given(leak, "exponent", 2.0))
    busy = min(load / f, 1.0) if f > 0 else 0.0
    idle_gated = _given(p, "idle_gated", 0.0)
    dyn = busy * model.dyn_mw(f)
    static = model.leak_mw(f) * (busy + (1.0 - busy) * (1.0 - idle_gated))
    return {"mw": round(dyn + static, 3), "dynamic_mw": round(dyn, 3), "static_mw": round(static, 3),
            "mv": model.mv(f)}


def _variant_dict(graph) -> dict[str, Any]:
    v = graph.variant
    return {"id": getattr(v, "id", None), "design_conditions": dict(v.design_conditions or {}),
            "routing_switch": dict(v.routing_switch or {})}


def _selected(sel, vdict) -> bool:
    return _match(vdict, {"when": sel.when or {}, "when_node_enabled": sel.when_node_enabled})


def pinned_clocks(node_config: dict[str, Any]) -> dict[str, float]:
    """Clock domains the node config fixes: ``dvfs.aud_freq_khz`` pins the ``AUD`` domain (as for a domain load)."""
    dvfs = node_config.get("dvfs") if isinstance(node_config, dict) else None
    aud = dvfs.get("aud_freq_khz") if isinstance(dvfs, dict) else None
    if isinstance(aud, bool) or not isinstance(aud, (int, float)) or not math.isfinite(aud) or aud <= 0:
        return {}
    return {"AUD": float(aud) / 1000.0}


def evaluate_subsystem(node_id: str, decl: dict[str, Any], caps: dict[str, Any], vdict: dict[str, Any],
                       node_ids: set[str] | None = None, pinned: dict[str, float] | None = None) -> dict:
    """``{"summary": <domain-load-shaped entry>, "detail": <report.subsystems[node]>}``; ValueError on an invalid
    declaration (as a domain load). ``node_ids``: the pipeline nodes the merged declaration may name.
    ``pinned``: clock domains fixed by the node config (``pinned_clocks``), used instead of the lowest level."""
    try:
        spec = SubsystemSpec.model_validate(decl)
    except Exception as exc:  # noqa: BLE001 - pydantic detail, refused like a bad domain load
        raise ValueError(f"{node_id}: invalid subsystem: {exc}") from None
    if node_ids is not None:
        unknown = sorted(spec.node_refs() - node_ids)
        if unknown:      # also after the variant patch (a patched bind / when_node_enabled)
            raise ValueError(f"{node_id}: subsystem names unknown nodes {unknown} (bind / when_node_enabled)")
    if spec.model != MODEL_ID:
        raise ValueError(f"{node_id}: unknown subsystem model {spec.model!r} (registered: ['{MODEL_ID}'])")
    units = {u.id: u for u in spec.units}
    streams = {s.id: s for s in spec.streams or []}
    stages = [s for s in spec.stages or [] if _selected(s, vdict)]
    active_ids = {s.id for s in stages}
    wakes = [w for w in spec.wake or [] if _selected(w, vdict)]

    # ---- load per unit (Mcycle/s)
    def stage_load(s) -> float:
        if s.mcps is not None:
            return float(s.mcps)
        if s.mcycles_per_period is not None:
            return float(s.mcycles_per_period) * 1000.0 / streams[str(s.stream)].period_ms
        return 0.0

    load = {u: 0.0 for u in units}
    for s in stages:
        load[s.unit] += stage_load(s)

    # ---- clock domains
    catalog_freqs = sorted(_catalog_defaults(caps or {}).get("freqs_mhz") or [])
    domains: dict[str, list[str]] = {}
    for u in spec.units:    # compute units always run on a clock; others only when they declare a domain
        if u.kind in COMPUTE_KINDS or u.clock_domain:
            domains.setdefault(u.clock_domain or u.id, []).append(u.id)
    freq: dict[str, float] = {}          # unit -> MHz
    domain_rows = {}
    infeasible: list[str] = []
    for dom, members in domains.items():
        # each unit's levels (its own freqs_mhz, else the catalog's); the shared clock takes common levels only
        per_unit = [set(units[m].freqs_mhz or catalog_freqs) for m in members]
        if any(not lv for lv in per_unit):
            raise ValueError(f"{node_id}: subsystem clock domain {dom} has a unit without operating points "
                             "(freqs_mhz or the IP catalog DVFS levels)")
        levels = sorted(set.intersection(*per_unit))
        if not levels:
            raise ValueError(f"{node_id}: subsystem clock domain {dom} units share no operating point")
        compute = [m for m in members if units[m].kind in COMPUTE_KINDS]
        fixed = (pinned or {}).get(dom)
        if fixed is not None:
            match = [x for x in levels if abs(x - fixed) < 1e-6]
            if not match:
                raise ValueError(f"{node_id}: subsystem clock domain {dom} is pinned to {fixed:g} MHz (node dvfs), "
                                 f"not one of its levels {levels}")
            f = match[0]
        else:
            f = next((x for x in levels if all(load[m] / x <= units[m].target_util + 1e-12 for m in compute)),
                     levels[-1])
        for m in members:
            freq[m] = f
            if load[m] / f > 1.0 + 1e-9:
                infeasible.append(f"{m} {load[m]:.1f} Mcycle/s > {f:.0f} MHz")
        domain_rows[dom] = {"units": members, "freq_mhz": round(f, 1), "levels_mhz": [round(x, 1) for x in levels],
                            "max_util": round(max((load[m] / f for m in compute), default=0.0), 4)}
        if fixed is not None:
            domain_rows[dom]["pinned"] = True

    # ---- power per unit
    used = {s.unit for s in stages}
    unit_rows, unattributed, total = [], [], 0.0
    for u in spec.units:
        row: dict[str, Any] = {"id": u.id, "kind": u.kind, "value_source": u.value_source}
        if u.kind in COMPUTE_KINDS:
            f = freq[u.id]
            row.update(load_mcps=round(load[u.id], 3), freq_mhz=round(f, 1), util=round(load[u.id] / f, 4),
                       target_util=u.target_util, clock_domain=u.clock_domain or u.id)
            if u.power is not None:
                row.update(_unit_power(node_id, u, load[u.id], f))
        elif u.kind in GATED_KINDS and u.id not in used:
            row.update(mw=0.0, gated=True)     # hw / interface without an active stage is off (e.g. the unused output)
        elif u.power is not None:
            row["mw"] = round(float(u.power["mw"]), 3)
        if "mw" in row:
            total += row["mw"]
        else:
            unattributed.append(u.id)
        if u.basis:
            row["basis"] = u.basis
        unit_rows.append(row)

    # ---- stages, deadline slack per stream
    stage_rows = []
    for s in stages:
        lo = stage_load(s)
        row = {"id": s.id, "kind": s.kind, "unit": s.unit, "load_mcps": round(lo, 3), "value_source": s.value_source}
        if s.stream:
            row["stream"] = s.stream
            if units[s.unit].kind in COMPUTE_KINDS and lo:
                row["ms_per_period"] = round(lo * streams[s.stream].period_ms / freq[s.unit], 4)
        for key in ("bind", "basis", "evidence_ref"):
            if getattr(s, key):
                row[key] = getattr(s, key)
        stage_rows.append(row)
    slack = []
    for sid, st in streams.items():
        on = sorted({s.unit for s in stages if s.stream == sid and units[s.unit].kind in COMPUTE_KINDS})
        if not on:
            continue
        worst = min(on, key=lambda u: 1.0 - load[u] / freq[u])
        slack.append({"stream": sid, "period_ms": round(st.period_ms, 4), "unit": worst,
                      "slack_ms": round(st.period_ms * (1.0 - load[worst] / freq[worst]), 4)})

    # ---- route latency
    route = None
    if spec.routes:
        active_routes = [r for r in spec.routes if _selected(r, vdict)]
        if len(active_routes) != 1:
            raise ValueError(f"{node_id}: subsystem needs exactly one active route in this variant, found "
                             f"{[r.id for r in active_routes]}")
        r = active_routes[0]
        off = [s for s in r.stages if s not in active_ids]
        if off:
            raise ValueError(f"{node_id}: subsystem route {r.id} stages {off} are not active in this variant")
        by_id = {s.id: s for s in stages}
        buffering, seen = 0.0, []
        work = 0.0
        for sid in r.stages:
            s = by_id[sid]
            if s.stream and s.stream not in seen:
                seen.append(s.stream)
                buffering += streams[s.stream].period_ms * streams[s.stream].periods
            if s.stream and units[s.unit].kind in COMPUTE_KINDS:
                work += stage_load(s) * streams[s.stream].period_ms / freq[s.unit]
        latency = buffering + work
        route = {"id": r.id, "kind": r.kind, "stages": list(r.stages), "streams": seen,
                 "buffering_ms": round(buffering, 4), "processing_ms": round(work, 4),
                 "latency_ms": round(latency, 4)}
        if r.latency_target_ms is not None:
            route["latency_target_ms"] = r.latency_target_ms
            route["latency_ok"] = latency <= r.latency_target_ms + 1e-9

    # ---- wake sources (M-5 input)
    wake_rows = []
    for w in wakes:
        if w.kind == "period_irq":          # the schema guarantees the field each kind needs
            rate = 1000.0 / streams[str(w.stream)].period_ms
        elif w.kind == "refill":
            rate = 1000.0 / float(w.every_ms or 0.0)
        else:
            rate = float(w.per_s or 0.0)
        if not math.isfinite(rate):
            raise ValueError(f"{node_id}: subsystem wake {w.kind} rate is not finite")
        row = {"kind": w.kind, "per_s": round(rate, 4)}
        for key in ("stream", "every_ms", "mb"):
            if getattr(w, key) is not None:
                row[key] = getattr(w, key)
        wake_rows.append(row)

    binds: dict[str, dict[str, Any]] = {}
    for s in stages:
        if s.bind:
            b = binds.setdefault(s.bind, {"stages": [], "load_mcps": 0.0})
            b["stages"].append(s.id)
            b["load_mcps"] = round(b["load_mcps"] + stage_load(s), 3)

    feasible = not infeasible
    main = max(domain_rows.items(), key=lambda kv: kv[1]["max_util"], default=(None, None))[1]
    detail = {
        "model": MODEL_ID, "mw": round(total, 3), "feasible": feasible, "domains": domain_rows, "units": unit_rows,
        "stages": stage_rows, "deadline_slack": slack, "wake": {"per_s": round(sum(r["per_s"] for r in wake_rows), 4),
                                                                 "sources": wake_rows},
        "unattributed_units": unattributed, "binds": binds, "value_source": spec.value_source,
        "basis": ("mcps-v1: unit load = sum of active stage MCPS; domain clock = lowest level keeping every unit at "
                  "or below its target util; cpu / dsp power util-vf-v1, hw constant; wake rates reported only"),
    }
    if route is not None:
        detail["route"] = route
    if spec.sram_kb is not None:
        detail["sram_kb"] = spec.sram_kb
    summary = {
        "model": MODEL_ID, "mw": round(total, 3), "feasible": feasible, "unattributed_units": unattributed,
        "freq_mhz": main["freq_mhz"] if main else None, "util": main["max_util"] if main else 0.0,
        "value_source": spec.value_source,
    }
    if infeasible:
        summary["reason"] = f"{node_id}: subsystem 부하가 최고 운영점을 넘음 — " + "; ".join(infeasible)
    if route is not None and route.get("latency_ok") is False:
        summary["note"] = (f"route {route['id']} latency {route['latency_ms']:.1f} ms > 목표 "
                           f"{route['latency_target_ms']:.1f} ms")
    return {"summary": summary, "detail": detail}
