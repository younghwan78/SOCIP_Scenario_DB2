"""Domain load models: power of IPs that are not pixel-pipeline engines (GPU, NPU, audio DSP) — review finding D-03.

A pipeline node on such an IP has no ``ppc`` / clock rule, so the compute model gives it 0 mW (``zero_power_ips``).
A domain load model turns a declared work rate into an operating point, a busy share and a power::

    work     = (mcycles_per_frame + mcycles_per_layer x input_layers) x (pixels / ref_pixels) ^ pixel_exponent x rate_hz
               (or mcycles_per_s, for a continuous load such as audio)                                       [Mcycle/s]
    f        = the fixed operating point (freq_mhz, or the node's dvfs.aud_freq_khz), else the governor:
               the lowest frequency of the table with work / f <= target_util (the highest one when none fits)
    util     = work / f                                  (> 1: the domain cannot keep up -> verdict fail)
    dynamic  = util x coeff x f x V(f)^2 / 1000          [mW]  (profiler convention, as the CPU energy model)
    static   = leak(V(f)) x (util + (1 - util) x (1 - idle_gated))
    leak(V)  = mw_at_ref x (V / ref_mv) ^ exponent

Registered models (``DOMAIN_MODELS``, like ``POWER_MODELS`` / ``LOAD_MODELS``): ``util-vf-v1``.

Declarations, merged in this order (later wins):

1. the IP catalog (read only): ``power_model`` coefficient (``dynamic_coeff_uw_per_mhz_v2`` or
   ``profiler_dynamic_coeff``), ``vf_table`` / ``vf_table_sample``, ``leakage`` / ``leakage_sample`` and the
   frequency table of ``dvfs_model`` (``freq_table_khz``, ``dvfs_table[].freq_core_khz`` or ``aud_qos_levels_khz``);
2. the scenario pipeline node ``domain_load: {model, coeff_uw_per_mhz_v2, vf, leakage, freqs_mhz, ...}`` —
   scenario-local assumptions, so the shared IP catalog (and every other scenario's input hash) stays as it is;
3. the variant ``node_configs.<node>.sim.domain_load`` (the work of this variant; ``none`` opts out).

Opt-in: a node with neither 2 nor 3 computes exactly as before (no engine revision change).
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from scenario_db.sim.domain_power import DomainPowerModel

_MERGE_KEYS = ("model", "coeff_uw_per_mhz_v2", "vf", "leakage", "freqs_mhz", "freq_mhz", "target_util",
               "idle_gated", "mcycles_per_frame", "mcycles_per_layer", "mcycles_per_s", "rate_hz", "ref_pixels", "pixel_exponent",
               "value_source", "basis")


class DomainModel(Protocol):
    id: str

    def estimate(self, *, node_id: str, cfg: dict[str, Any], rate_hz: float, pixels: float | None,
                 layers: float | None = None) -> dict[str, Any]:
        ...


def _num(cfg: dict[str, Any], key: str, node_id: str, *, lo: float | None = 0.0, hi: float | None = None,
         default: float | None = None) -> float | None:
    value = cfg.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{node_id}: domain_load.{key} must be a number, got {value!r}")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{node_id}: domain_load.{key} must be a number, got {value!r}") from None
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(f"{node_id}: domain_load.{key} = {x:g} is out of range")
    return x


class UtilVfV1:
    id = "util-vf-v1"

    def estimate(self, *, node_id, cfg, rate_hz, pixels, layers=None):
        coeff = _num(cfg, "coeff_uw_per_mhz_v2", node_id)
        vf = sorted((float(r["mhz"]), float(r["mv"])) for r in (cfg.get("vf") or []) if r.get("mhz") and r.get("mv"))
        if not coeff or not vf:
            raise ValueError(f"{node_id}: domain load {self.id} needs coeff_uw_per_mhz_v2 and a vf table "
                             "(the IP catalog power_model or the pipeline node's domain_load)")
        leak = cfg.get("leakage") or {}
        model = DomainPowerModel(name=node_id, ip_ref="", coeff_uw_per_mhz_v2=coeff, vf=tuple(vf),
                                 leak_mw_at_ref=float(leak.get("mw_at_ref") or 0.0),
                                 leak_ref_mv=float(leak.get("ref_mv") or 750.0),
                                 leak_exponent=float(leak.get("exponent") or 2.0))
        per_s = _num(cfg, "mcycles_per_s", node_id)
        per_frame = _num(cfg, "mcycles_per_frame", node_id)
        per_layer = _num(cfg, "mcycles_per_layer", node_id)
        if per_s is None and per_frame is None and per_layer is None:
            raise ValueError(f"{node_id}: domain load {self.id} needs mcycles_per_frame, mcycles_per_layer or mcycles_per_s")
        if per_layer is not None and not layers:
            raise ValueError(f"{node_id}: domain_load.mcycles_per_layer needs the node's sim.input_layers")
        scale = 1.0
        if per_s is None:
            ref_px = _num(cfg, "ref_pixels", node_id)
            exp = _num(cfg, "pixel_exponent", node_id, default=1.0)
            if ref_px and pixels:
                scale = (pixels / ref_px) ** exp
            rate = _num(cfg, "rate_hz", node_id, default=rate_hz) or 0.0
            frame = (per_frame or 0.0) + (per_layer or 0.0) * float(layers or 0)
            work = frame * scale * rate
        else:
            rate = None
            work = per_s
        target = _num(cfg, "target_util", node_id, lo=0.05, hi=1.0, default=0.85)
        idle_gated = _num(cfg, "idle_gated", node_id, hi=1.0, default=0.0)
        freqs = sorted({float(f) for f in (cfg.get("freqs_mhz") or []) if float(f) > 0}) or [f for f, _ in vf]
        fixed = _num(cfg, "freq_mhz", node_id)
        if fixed:
            f, chosen_by = fixed, "fixed"
        else:
            f = next((x for x in freqs if work / x <= target + 1e-12), freqs[-1])
            chosen_by = "governor"
        util = work / f if f > 0 else 0.0
        busy = min(util, 1.0)
        dyn = busy * model.dyn_mw(f)
        static = model.leak_mw(f) * (busy + (1.0 - busy) * (1.0 - idle_gated))
        feasible = util <= 1.0 + 1e-9
        out = {
            "model": self.id, "work_mcycles_s": round(work, 3), "freq_mhz": round(f, 1), "freq_by": chosen_by,
            "f_max_mhz": round(max(freqs[-1], f), 1), "mv": model.mv(f), "util": round(util, 4),
            "target_util": target, "dynamic_mw": round(dyn, 3), "static_mw": round(static, 3),
            "mw": round(dyn + static, 3), "feasible": feasible,
            "value_source": str(cfg.get("value_source") or "assumed"),
        }
        if rate is not None:
            out["rate_hz"] = round(rate, 4)
            out["pixel_scale"] = round(scale, 4)
            if per_layer is not None:
                out["layers"] = float(layers or 0)
        if cfg.get("basis"):
            out["basis"] = str(cfg["basis"])
        if not feasible:
            out["reason"] = (f"{node_id}: domain 부하 {work:.0f} Mcycle/s > {f:.0f} MHz (util {util:.2f}) — "
                             "최고 운영점에서도 처리 못함")
        elif util > target + 1e-9:
            out["note"] = f"util {util:.2f} > 목표 {target:.2f} (최고 운영점)"
        return out


DOMAIN_MODELS: dict[str, DomainModel] = {UtilVfV1.id: UtilVfV1()}


def _catalog_defaults(caps: dict[str, Any]) -> dict[str, Any]:
    pm = caps.get("power_model") or {}
    out: dict[str, Any] = {}
    coeff = pm.get("dynamic_coeff_uw_per_mhz_v2", pm.get("profiler_dynamic_coeff"))
    if isinstance(coeff, (int, float)) and not isinstance(coeff, bool) and coeff > 0:
        out["coeff_uw_per_mhz_v2"] = float(coeff)
    table = pm.get("vf_table") or pm.get("vf_table_sample")
    if table:
        out["vf"] = table
    leak = pm.get("leakage") or pm.get("leakage_sample")
    if leak:
        out["leakage"] = leak
    dv = caps.get("dvfs_model") or {}
    khz = dv.get("freq_table_khz") or [r.get("freq_core_khz") for r in dv.get("dvfs_table") or []] \
        or dv.get("aud_qos_levels_khz") or []
    mhz = sorted({float(k) / 1000.0 for k in khz if isinstance(k, (int, float)) and k > 0})
    if mhz:
        out["freqs_mhz"] = mhz
    return out


def domain_load_config(caps: dict[str, Any], node: dict[str, Any] | None, node_config: dict[str, Any]) -> dict[str, Any] | None:
    """The merged declaration of one node, or None when the node does not opt in."""
    sim = node_config.get("sim") or {}
    own = sim.get("domain_load")
    scenario = (node or {}).get("domain_load")
    if isinstance(own, str) and own.lower() == "none":
        return None
    if not isinstance(own, dict) and not isinstance(scenario, dict):
        return None
    cfg = _catalog_defaults(caps or {})
    for layer in (scenario, own):
        if isinstance(layer, dict):
            cfg.update({k: v for k, v in layer.items() if k in _MERGE_KEYS})
            unknown = sorted(set(layer) - set(_MERGE_KEYS))
            if unknown:
                raise ValueError(f"{(node or {}).get('id')}: unknown domain_load keys {unknown}")
    aud = (node_config.get("dvfs") or {}).get("aud_freq_khz") if isinstance(node_config.get("dvfs"), dict) else None
    if "freq_mhz" not in cfg and isinstance(aud, (int, float)) and aud > 0:
        cfg["freq_mhz"] = float(aud) / 1000.0  # the node's declared AUD operating point
    cfg.setdefault("model", UtilVfV1.id)
    return cfg


def domain_loads(graph, active: set[str], default_rate_hz: float) -> dict[str, dict[str, Any]]:
    """``{node: estimate}`` of every active node that declares a domain load (empty when none does)."""
    nodes = {str(n.get("id")): n for n in ((graph.scenario.pipeline or {}).get("nodes") or [])}
    configs = graph.variant.node_configs or {}
    out: dict[str, dict[str, Any]] = {}
    for node_id in sorted(active):
        node = nodes.get(node_id)
        if node is None:
            continue
        node_config = configs.get(node_id) or {}
        ip = graph.ip_catalog.get(str(node.get("ip_ref") or ""))
        # R-4: a declared subsystem (mcps-v1) is the node's load, in place of its domain_load
        from scenario_db.sim.subsystem import _variant_dict, evaluate_subsystem, subsystem_config

        decl = subsystem_config(node, node_config)
        if decl is not None:
            res = evaluate_subsystem(node_id, decl, getattr(ip, "capabilities", None) or {}, _variant_dict(graph))
            out[node_id] = {**res["summary"], "subsystem": res["detail"]}
            continue
        cfg = domain_load_config(getattr(ip, "capabilities", None) or {}, node, node_config)
        if cfg is None:
            continue
        model = DOMAIN_MODELS.get(str(cfg["model"]))
        if model is None:
            raise ValueError(f"{node_id}: unknown domain load model {cfg['model']!r} (registered: {sorted(DOMAIN_MODELS)})")
        sim = node_config.get("sim") or {}
        w, h = sim.get("width"), sim.get("height")
        pixels = float(w) * float(h) if w and h else None
        rate = float(sim.get("fps") or default_rate_hz)
        out[node_id] = model.estimate(node_id=node_id, cfg=cfg, rate_hz=rate, pixels=pixels, layers=sim.get("input_layers"))
    return out
