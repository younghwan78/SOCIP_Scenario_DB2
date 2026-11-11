"""Assumed-input sensitivity of one predicted case: tornado rows and break-even changes.

The spec-stage prediction rests on inputs that are assumed (catalog unit power, the BW power
coefficient, compression ratios, SW timing, declared GPU / NPU loads, SAMPLE DVFS voltages).
Each input is moved by ±``pct`` % on its own and the change of the case's total power is read
from the case's own power breakdown (``prediction_payload``): IP power is linear in the unit
power, BW power in its coefficient and in the buffer's compressed size, CPU power in the SW
time, IP power in V². No re-simulation runs, so this is a first-order (linear) estimate around
the case — enough to rank what to measure first, not a replacement for re-exploring.

Break-even = the smallest change of one input that crosses a limit (power budget, sustained
current as mW) or the SW growth the timing verdict still passed.
"""

from __future__ import annotations

from typing import Any

DEFAULT_PCT = 20.0
VOLTAGE_PCT = 5.0
METHOD = "linear one-at-a-time around the predicted case (no re-simulation)"


def _r(x: float, n: int = 3) -> float:
    return round(float(x), n)


def assumed_sensitivity(
    payload: dict[str, Any],
    *,
    sample_dvfs: bool = False,
    ratio_sources: dict[str, str] | None = None,
    sw_growth_tolerance: float | None = None,
    sw_growth_tested_max: float | None = None,
    limits: dict[str, float] | None = None,
    pct: float = DEFAULT_PCT,
    voltage_pct: float = VOLTAGE_PCT,
    sw_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tornado rows for one case (``prediction_payload`` shape), largest swing first.

    ``sw_items``: the objective slice's stage SW items (the frozen payload drops them); each has
    ``kind`` and the timing ``source`` (``assumed`` / measured / timeline).
    """
    power = payload.get("power") or {}
    total = float(power.get("total_mw") or 0.0)
    f = pct / 100.0
    limits = {k: float(v) for k, v in (limits or {}).items() if v is not None}
    rows: list[dict[str, Any]] = []

    def add(key: str, label: str, source: str, component_mw: float, low: float, high: float, *,
            step_pct: float = pct, timing: dict[str, Any] | None = None) -> None:
        if component_mw <= 0:
            return
        lo, hi = component_mw * low, component_mw * high
        row: dict[str, Any] = {"key": key, "label": label, "source": source, "step_pct": step_pct,
                               "component_mw": _r(component_mw), "delta_low_mw": _r(lo), "delta_high_mw": _r(hi),
                               "swing_mw": _r(abs(hi - lo)), "swing_pct": _r(100 * abs(hi - lo) / total, 2) if total else None}
        # break-even: % change of this input that reaches each limit (linear in the component)
        crosses, break_even = [], {}
        gain = 2.0 if key.startswith("vdd:") else 1.0  # % of the component per % of the input (P ∝ V²)
        for name, limit_mw in limits.items():
            per_pct = component_mw * gain / 100.0
            break_even[name] = _r((limit_mw - total) / per_pct, 1) if per_pct else None
            # the limit verdict differs between the two ends of the range
            if (total + min(lo, hi) > limit_mw) != (total + max(lo, hi) > limit_mw):
                crosses.append(name)
        row["break_even_pct"] = break_even
        row["crosses"] = crosses
        if timing:
            row["timing"] = timing
        rows.append(row)

    for ip in payload.get("ips") or []:
        mw = float(ip.get("power_mw") or 0.0)
        add(f"ip:{ip.get('node')}", f"{ip.get('node')} unit power", "IP catalog", mw, -f, f)
    bw = float(power.get("bw_mw") or 0.0)
    add("bw:coeff", "BW power 계수", "BW power model", bw, -f, f)
    # compressed buffers: BW of the buffer = raw x ratio; power per MB/s from the case's own BW power
    mbs = float(payload.get("bw_mbs") or 0.0)
    mw_per_mbs = bw / mbs if mbs else 0.0
    for b in payload.get("buffers") or []:
        if not b.get("compressed"):
            continue
        src = (ratio_sources or {}).get(b["buffer"], "catalog")
        size_mw = float(b.get("raw_mbs") or 0.0) * float(b.get("comp_ratio") or 1.0) * mw_per_mbs
        add(f"ratio:{b['buffer']}", f"{b['buffer']} 압축 ratio ({b.get('mode') or ''})", f"ratio {src}", size_mw, -f, f)
    for ip, mw in (payload.get("assumed_by_ip") or {}).items():
        add(f"load:{ip}", f"{ip} 가정 부하", "design_conditions", float(mw or 0.0), -f, f)
    # SW time: CPU power follows the SW time (active ratio); the timing verdict passed up to the tolerance
    if sw_items is None:
        sw_items = [i for st in (payload.get("stages") or {}).values() for i in (st.get("sw_items") or [])]
    sw_items = [i for i in sw_items if i.get("kind") == "sw"]
    n_sw = len(sw_items)
    n_assumed = sum(1 for i in sw_items if str(i.get("source") or "") == "assumed")
    cpu = float(power.get("cpu_mw") or 0.0)
    scale = float(payload.get("runtime_scale") or 1.0)
    timing = None
    if sw_growth_tolerance is not None:
        headroom = 100 * (sw_growth_tolerance / scale - 1)
        # passing at the largest tested growth: the real tolerance is at least that (break-even is a lower bound)
        at_least = sw_growth_tested_max is not None and sw_growth_tolerance >= sw_growth_tested_max
        timing = {"growth_tolerance": sw_growth_tolerance, "break_even_pct": _r(headroom, 1), "at_least": at_least,
                  "fails_at_high": not at_least and scale * (1 + f) > sw_growth_tolerance * (1 + 1e-9)}
    if n_sw:
        label = f"SW timing ({'가정' if n_assumed else '입력'} {n_assumed or n_sw}/{n_sw} task)"
        add("sw:runtime", label, "assumed" if n_assumed else "profile / measured", cpu, -f, f, timing=timing)
    if sample_dvfs:
        by_group: dict[str, float] = {}
        for ip in payload.get("ips") or []:
            if ip.get("dvfs_group"):
                by_group[str(ip["dvfs_group"])] = by_group.get(str(ip["dvfs_group"]), 0.0) + float(ip.get("power_mw") or 0.0)
        v = voltage_pct / 100.0
        for group, mw in sorted(by_group.items()):
            add(f"vdd:{group}", f"{group} 전압 (SAMPLE DVFS)", "SAMPLE DVFS", mw, (1 - v) ** 2 - 1, (1 + v) ** 2 - 1,
                step_pct=voltage_pct)
    rows.sort(key=lambda r: (-r["swing_mw"], r["key"]))
    return {"method": METHOD, "pct": pct, "voltage_pct": voltage_pct, "total_mw": _r(total),
            "limits": {k: _r(v) for k, v in limits.items()}, "rows": rows}


def top_inputs(results: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    """Inputs with the largest swing over several cases (one row per input label, worst case kept)."""
    best: dict[str, dict[str, Any]] = {}
    for res in results:
        for row in res.get("rows") or []:
            label = row["label"]
            cur = best.get(label)
            if cur is None or row["swing_mw"] > cur["swing_mw"]:
                best[label] = {**row, "count": (cur or {}).get("count", 0) + 1, "crosses_any": bool(row["crosses"]) or bool((cur or {}).get("crosses_any"))}
            else:
                cur["count"] += 1
                cur["crosses_any"] = cur["crosses_any"] or bool(row["crosses"])
    return sorted(best.values(), key=lambda r: (-r["swing_mw"], r["label"]))[:n]


def variant_sensitivity(v: dict[str, Any], chosen: dict[str, Any] | None = None, *, sample_dvfs: bool = False,
                        pct: float = DEFAULT_PCT, voltage_pct: float = VOLTAGE_PCT) -> dict[str, Any] | None:
    """Sensitivity of a stored exploration variant: its registered case (``chosen`` frozen metrics) or the
    recommended case (baseline when nothing is eligible). None when the summary lacks the breakdown."""
    obj = v.get("objective_slice") or {}
    payload = chosen
    if not payload or not payload.get("power"):
        case = v.get("recommended") or v.get("baseline")
        if not case or not obj.get("ips") or "stages" not in obj:
            return None
        from scenario_db.sim.arch_exploration import prediction_payload

        try:
            payload = prediction_payload(obj, case, v.get("buffers") or [])
        except (KeyError, TypeError):
            return None
    sources = {}
    for b in v.get("buffers") or []:
        mode = (payload.get("compression_modes") or {}).get(b.get("buffer"))
        m = next((x for x in b.get("modes") or [] if x.get("mode") == mode), None) if mode else None
        sources[b.get("buffer")] = str((m or b).get("ratio_source") or "catalog")
    budget = (v.get("power_budget") or {}).get("mw") or ((v.get("constraints") or {}).get("power_budget_mw"))
    tolerance = (v.get("sw_margin") or {}).get("growth_tolerance")
    tested = (v.get("sw_margin") or {}).get("growth_tested_max")
    items = [i for st in (obj.get("stages") or {}).values() for i in (st.get("sw_items") or [])]
    return assumed_sensitivity(payload, sample_dvfs=sample_dvfs, ratio_sources=sources, sw_items=items,
                               sw_growth_tolerance=tolerance, sw_growth_tested_max=tested,
                               limits={"power budget": budget} if budget else None,
                               pct=pct, voltage_pct=voltage_pct)
