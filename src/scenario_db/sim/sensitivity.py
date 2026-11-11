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
METHOD = ("one input at a time around the predicted case: linear per input, SAMPLE voltage by the engine V law, "
          "profile CPU from the stored growth slices (no re-simulation)")


def _r(x: float, n: int = 3) -> float:
    return round(float(x), n)


def assumed_sensitivity(
    payload: dict[str, Any],
    *,
    sample_dvfs: bool = False,
    ratio_rows: list[dict[str, Any]] | None = None,
    sw_growth_tolerance: float | None = None,
    sw_growth_tested_max: float | None = None,
    sw_profile_slices: dict[float, float] | None = None,
    limits: dict[str, float] | None = None,
    pct: float = DEFAULT_PCT,
    voltage_pct: float = VOLTAGE_PCT,
    sw_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tornado rows for one case (``prediction_payload`` shape), largest swing first.

    ``ratio_rows``: compressed buffers of the case, each ``{buffer, mode, ratio, source, slope_mw}`` with
    ``slope_mw`` = d(power)/d(ratio) from the buffer's own DMA ports (LLC weight included).
    ``sw_items``: the objective slice's stage SW items (the frozen payload drops them).
    ``sw_growth_tolerance``: SW growth the case still passes with its DVFS held (fixed tolerance).
    ``sw_profile_slices``: measured-profile CPU (+ CPU BW) power per runtime scale; with it the SW row
    reads the stored growth slices instead of the flat linear CPU rule (OPP, leakage, DSU and CPU BW
    move non-linearly).
    """
    power = payload.get("power") or {}
    total = float(power.get("total_mw") or 0.0)
    f = pct / 100.0
    limits = {k: float(v) for k, v in (limits or {}).items() if v is not None}
    rows: list[dict[str, Any]] = []
    notes: list[str] = []

    def add(key: str, label: str, source: str, component_mw: float, lo: float, hi: float, *, per_pct_mw: float,
            step_pct: float = pct, timing: dict[str, Any] | None = None, note: str | None = None) -> None:
        if component_mw <= 0 or (lo == 0 and hi == 0):
            return
        row: dict[str, Any] = {"key": key, "label": label, "source": source, "step_pct": step_pct,
                               "component_mw": _r(component_mw), "delta_low_mw": _r(lo), "delta_high_mw": _r(hi),
                               "swing_mw": _r(abs(hi - lo)), "swing_pct": _r(100 * abs(hi - lo) / total, 2) if total else None}
        # break-even: % change of this input that reaches each limit (first order)
        crosses, break_even = [], {}
        for name, limit_mw in limits.items():
            break_even[name] = _r((limit_mw - total) / per_pct_mw, 1) if per_pct_mw else None
            # the limit verdict differs between the two ends of the range
            if (total + min(lo, hi) > limit_mw) != (total + max(lo, hi) > limit_mw):
                crosses.append(name)
        row["break_even_pct"] = break_even
        row["crosses"] = crosses
        if timing:
            row["timing"] = timing
        if note:
            row["note"] = note
        rows.append(row)

    for ip in payload.get("ips") or []:
        # unit power scales the dynamic part only; leakage is characterised separately (v2-vf)
        dyn = max(0.0, float(ip.get("power_mw") or 0.0) - float(ip.get("leakage_power_mw") or 0.0))
        add(f"ip:{ip.get('node')}", f"{ip.get('node')} unit power", "IP catalog", dyn, -f * dyn, f * dyn,
            per_pct_mw=dyn / 100.0)
    bw = float(power.get("bw_mw") or 0.0)
    add("bw:coeff", "BW power 계수", "BW power model", bw, -f * bw, f * bw, per_pct_mw=bw / 100.0)
    for rr in ratio_rows or []:
        ratio, slope = float(rr["ratio"]), float(rr["slope_mw"])
        part = ratio * slope
        # a compressed buffer never exceeds its raw size: the upper ratio stops at 1.0
        lo, hi = -f * ratio * slope, (min(1.0, ratio * (1 + f)) - ratio) * slope
        add(f"ratio:{rr['buffer']}", f"{rr['buffer']} 압축 ratio ({rr.get('mode') or ''})", f"ratio {rr.get('source') or 'catalog'}",
            part, lo, hi, per_pct_mw=part / 100.0)
    for ip, mw in (payload.get("assumed_by_ip") or {}).items():
        mw = float(mw or 0.0)
        add(f"load:{ip}", f"{ip} 가정 부하", "design_conditions", mw, -f * mw, f * mw, per_pct_mw=mw / 100.0)
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
        source = "assumed" if n_assumed else "profile / measured"
        if sw_profile_slices is not None:
            # measured-profile CPU: read the stored growth slices (no linear rule)
            def at(x: float) -> float | None:
                return next((v for k, v in sw_profile_slices.items() if abs(k - x) < 1e-6), None)
            base, high, low = at(scale), at(scale * (1 + f)), at(scale * (1 - f))
            if base is None or high is None:
                notes.append(f"SW timing: profile CPU — ×{scale * (1 + f):g} growth slice 없음 (탐색 축에 추가하면 계산)")
            else:
                hi = high - base
                lo = (low - base) if low is not None else 0.0
                add("sw:runtime", label, source, cpu, lo, hi, per_pct_mw=hi / pct, timing=timing,
                    note=None if low is not None else f"증가 방향만 (×{scale * (1 - f):g} slice 없음)")
        else:
            add("sw:runtime", label, source, cpu, -f * cpu, f * cpu, per_pct_mw=cpu / 100.0, timing=timing)
    if sample_dvfs:
        from scenario_db.sim.arch_exploration import _ip_power_at

        v = voltage_pct / 100.0
        by_group: dict[str, list[float]] = {}
        for ip in payload.get("ips") or []:
            volt = float(ip.get("voltage_mv") or 0.0)
            if not ip.get("dvfs_group") or volt <= 0 or not ip.get("power_mw"):
                continue
            clock = float(ip.get("set_clock_mhz") or 0.0)
            # the engine's own law at the same clock: dynamic x V², leakage x V^k
            d = by_group.setdefault(str(ip["dvfs_group"]), [0.0, 0.0, 0.0])
            d[0] += float(ip["power_mw"])
            d[1] += _ip_power_at(ip, volt * (1 - v), clock) - float(ip["power_mw"])
            d[2] += _ip_power_at(ip, volt * (1 + v), clock) - float(ip["power_mw"])
        for group, (mw, lo, hi) in sorted(by_group.items()):
            add(f"vdd:{group}", f"{group} 전압 (SAMPLE DVFS)", "SAMPLE DVFS", mw, lo, hi,
                per_pct_mw=(hi - lo) / (2 * voltage_pct), step_pct=voltage_pct)
    rows.sort(key=lambda r: (-r["swing_mw"], r["key"]))
    return {"method": METHOD, "pct": pct, "voltage_pct": voltage_pct, "total_mw": _r(total),
            "limits": {k: _r(v) for k, v in limits.items()}, "rows": rows, **({"notes": notes} if notes else {})}


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


def _ratio_rows(buffers: list[dict[str, Any]], modes: dict[str, str]) -> list[dict[str, Any]]:
    """Compressed buffers of a case with d(power)/d(ratio) from their own DMA ports.

    The slope belongs to the buffer's ports (LLC weight, direction), not to the mode: the case's chosen
    mode (its delta vs the buffer's current ratio), else the current saving (OFF vs now), else any
    priced mode of the buffer. A buffer that already ships compressed and keeps it is included.
    """
    out = []
    for b in buffers:
        bid = b.get("buffer")
        base_ratio = float(b.get("base_comp_ratio") or 1.0) if b.get("base_compression") else 1.0
        priced = [m for m in b.get("modes") or [] if m.get("comp_ratio") is not None
                  and abs(float(m["comp_ratio"]) - base_ratio) > 1e-9]

        def slope_of(m: dict[str, Any]) -> float:
            return float(m.get("delta_mw") or 0.0) / (float(m["comp_ratio"]) - base_ratio)
        mode = modes.get(bid)
        if mode:
            m = next((x for x in priced if x.get("mode") == mode), None)
            if m is None:
                continue
            out.append({"buffer": bid, "mode": mode, "ratio": float(m["comp_ratio"]),
                        "source": str(m.get("ratio_source") or "catalog"), "slope_mw": slope_of(m)})
        elif b.get("base_compression"):
            cur = b.get("current_saving") or {}
            if base_ratio < 1.0 and float(cur.get("saving_mw") or 0.0) > 0:
                slope = float(cur["saving_mw"]) / (1.0 - base_ratio)
            elif priced:
                slope = slope_of(priced[0])
            else:
                continue
            out.append({"buffer": bid, "mode": b["base_compression"], "ratio": base_ratio,
                        "source": "scenario (현재 압축)", "slope_mw": slope})
    return [r for r in out if r["slope_mw"] > 0]


def variant_sensitivity(v: dict[str, Any], chosen: dict[str, Any] | None = None, *, sample_dvfs: bool = False,
                        pct: float = DEFAULT_PCT, voltage_pct: float = VOLTAGE_PCT) -> dict[str, Any] | None:
    """Sensitivity of a stored exploration variant: its registered case (``chosen`` frozen metrics) or the
    recommended case (baseline when nothing is eligible). None when the summary lacks the breakdown.
    ``sample_dvfs``: the DVFS table of the run this variant came from is a SAMPLE."""
    obj = v.get("objective_slice") or {}
    rec = v.get("recommended")
    payload = chosen
    if not payload or not payload.get("power"):
        case = rec or v.get("baseline")
        if not case or not obj.get("ips") or "stages" not in obj:
            return None
        from scenario_db.sim.arch_exploration import prediction_payload

        try:
            payload = prediction_payload(obj, case, v.get("buffers") or [])
        except (KeyError, TypeError):
            return None
    modes = dict(payload.get("compression_modes") or {})
    for bid in payload.get("compression") or []:
        modes.setdefault(bid, "")
    budget = (v.get("power_budget") or {}).get("mw") or ((v.get("constraints") or {}).get("power_budget_mw"))
    margin = v.get("sw_margin") or {}
    # the SW headroom with the case's DVFS held; it is the recommended case's, so only for that case
    same = rec is not None and sorted(payload.get("compression") or []) == sorted(rec.get("compression") or []) \
        and dict(payload.get("dvfs") or {}) == dict(rec.get("dvfs") or {})
    tolerance = margin.get("growth_tolerance_fixed") if same else None
    profile = None
    if str(obj.get("cpu_basis") or payload.get("cpu_basis") or "").startswith("profile"):
        stat = payload.get("statistic") or (v.get("objective") or {}).get("statistic")
        profile = {float(s["runtime_scale"]): float((s.get("power") or {}).get("cpu_mw") or 0.0)
                   + float((s.get("power") or {}).get("bw_sw_mw") or 0.0)
                   for s in v.get("slices") or [] if s.get("statistic") == stat and s.get("runtime_scale") is not None}
    items = [i for st in (obj.get("stages") or {}).values() for i in (st.get("sw_items") or [])]
    return assumed_sensitivity(payload, sample_dvfs=sample_dvfs, ratio_rows=_ratio_rows(v.get("buffers") or [], modes),
                               sw_items=items, sw_growth_tolerance=tolerance,
                               sw_growth_tested_max=margin.get("growth_tested_max"), sw_profile_slices=profile,
                               limits={"power budget": budget} if budget else None, pct=pct, voltage_pct=voltage_pct)


def is_sample_dvfs(ref: Any) -> bool:
    return bool(ref and "sample" in str(ref).lower())
