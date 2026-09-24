"""Why did the predicted power change? Exact additive decomposition of two predictions.

Power = CPU(SW) + HW(IP core) + BW(DMA)
- CPU: per SW task (runtime x statistic x growth -> busy time)
- HW : per IP, P = activity x (V/710)^2 -> two-factor LMDI
       dP = L(P1, P0) * [ln(a1/a0) + ln((V1/V0)^2)], L = logarithmic mean
       activity = pixel throughput x unit power (size, fps, mode, cores)
- BW : DMA traffic before compression (size, fps, topology) + per-buffer compression saving

Terms sum to the total delta; the residual is reported (rounding only).
"""

from __future__ import annotations

import math
from typing import Any


def _lmean(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return a if abs(a - b) < 1e-12 else (a - b) / (math.log(a) - math.log(b))


def attribute(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    factors: list[dict[str, Any]] = []

    def add(category: str, item: str, delta: float, detail: str = "") -> None:
        if abs(delta) >= 5e-3:
            factors.append({"category": category, "item": item, "delta_mw": round(delta, 3), "detail": detail})

    # CPU (SW)
    c0, c1 = old.get("cpu_by_task") or {}, new.get("cpu_by_task") or {}
    for task in sorted(set(c0) | set(c1)):
        a, b = float(c0.get(task, 0.0)), float(c1.get(task, 0.0))
        if task not in c0:
            add("SW task 추가", task, b, "new SW task")
        elif task not in c1:
            add("SW task 제거", task, -a, "SW task removed")
        else:
            add("SW runtime", task, b - a, "runtime/latency statistic or growth")
    cpu_other = (new["power"]["cpu_mw"] - sum(c1.values())) - (old["power"]["cpu_mw"] - sum(c0.values()))
    add("SW runtime", "(unlisted)", cpu_other)

    # HW (IP core) — two-factor LMDI
    i0 = {ip["node"]: ip for ip in old.get("ips") or []}
    i1 = {ip["node"]: ip for ip in new.get("ips") or []}
    for node in sorted(set(i0) | set(i1)):
        ia, ib = i0.get(node), i1.get(node)
        if ia is None and ib is not None:
            add("IP 추가", node, float(ib["power_mw"]), "IP enabled in the new prediction")
            continue
        if ib is None and ia is not None:
            add("IP 제거", node, -float(ia["power_mw"]), "IP no longer active")
            continue
        assert ia is not None and ib is not None
        p0, p1 = float(ia["power_mw"]), float(ib["power_mw"])
        if p0 <= 0 or p1 <= 0:
            add("IP workload", node, p1 - p0, "zero-power endpoint")
            continue
        w = _lmean(p1, p0)
        act = w * math.log(max(ib["activity_mw"], 1e-12) / max(ia["activity_mw"], 1e-12))
        v0, v1 = float(ia["voltage_mv"] or 0), float(ib["voltage_mv"] or 0)
        volt = w * math.log((v1 / v0) ** 2) if v0 > 0 and v1 > 0 else 0.0
        add("IP workload", node, act, "size/fps/mode/cores")
        lv = f"L{ia.get('dvfs_level')}→L{ib.get('dvfs_level')}" if ia.get("dvfs_level") != ib.get("dvfs_level") else ""
        add("IP DVFS 전압", node, volt, f"{v0:.1f}→{v1:.1f} mV {lv}".strip())
    hw_other = (new["power"]["hw_mw"] - sum(float(x["power_mw"]) for x in i1.values())) - (
        old["power"]["hw_mw"] - sum(float(x["power_mw"]) for x in i0.values())
    )
    add("IP workload", "(unlisted)", hw_other)

    # BW (DMA): traffic before compression + compression per buffer
    if "base_bw_ip_mw" in old and "base_bw_ip_mw" in new:
        for who, label in (("ip", "IP BW"), ("cpu", "CPU BW")):
            add("BW traffic", label, float(new[f"base_bw_{who}_mw"]) - float(old[f"base_bw_{who}_mw"]),
                f"{old[f'base_bw_{who}_mbs']:.0f}→{new[f'base_bw_{who}_mbs']:.0f} MB/s uncompressed (size/fps/topology)")
    else:  # a prediction from engine rev 1 has no IP/CPU BW split
        add("BW traffic", "uncompressed traffic", float(new.get("base_bw_mw", 0.0)) - float(old.get("base_bw_mw", 0.0)),
            f"{old.get('base_bw_mbs', 0):.0f}→{new.get('base_bw_mbs', 0):.0f} MB/s (size/fps/topology)")
    b0 = {b["buffer"]: b for b in old.get("buffers") or []}
    b1 = {b["buffer"]: b for b in new.get("buffers") or []}
    for buf in sorted(set(b0) | set(b1)):
        s0 = float(b0.get(buf, {}).get("delta_mw", 0.0))
        s1 = float(b1.get(buf, {}).get("delta_mw", 0.0))
        on0, on1 = bool(b0.get(buf, {}).get("compressed")), bool(b1.get(buf, {}).get("compressed"))
        detail = {(False, True): "compression ON", (True, False): "compression OFF"}.get((on0, on1), "ratio/traffic")
        add("Compression", buf, s1 - s0, detail)

    total = new["power"]["total_mw"] - old["power"]["total_mw"]
    explained = sum(f["delta_mw"] for f in factors)
    by_cat: dict[str, float] = {}
    for f in factors:
        by_cat[f["category"]] = by_cat.get(f["category"], 0.0) + f["delta_mw"]
    return {
        "old_total_mw": round(old["power"]["total_mw"], 3),
        "new_total_mw": round(new["power"]["total_mw"], 3),
        "delta_mw": round(total, 3),
        "delta_pct": round(100 * total / old["power"]["total_mw"], 2) if old["power"]["total_mw"] else None,
        "components": {
            k: round(new["power"][k] - old["power"][k], 3) for k in ("cpu_mw", "hw_mw", "bw_mw")
        } | {
            k: round(new["power"].get(k, 0.0) - old["power"].get(k, 0.0), 3)
            for k in ("bw_ip_mw", "bw_cpu_mw") if k in new["power"] and k in old["power"]
        },
        "by_category": {k: round(v, 3) for k, v in sorted(by_cat.items(), key=lambda x: -abs(x[1]))},
        "factors": sorted(factors, key=lambda f: -abs(f["delta_mw"])),
        "residual_mw": round(total - explained, 4),
        "context_changes": context_changes(old, new),
    }


def context_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, label in (("fps", "fps"), ("statistic", "SW 통계"), ("runtime_scale", "SW 증가율"),
                       ("eis_on", "EIS"), ("base_bw_mbs", "BW traffic (MB/s)")):
        if old.get(key) != new.get(key):
            out.append({"item": label, "old": old.get(key), "new": new.get(key)})
    c0, c1 = set(old.get("compression") or []), set(new.get("compression") or [])
    if c0 != c1:
        out.append({"item": "compression buffers", "old": sorted(c0 - c1), "new": sorted(c1 - c0)})
    d0, d1 = old.get("dvfs") or {}, new.get("dvfs") or {}
    for dom in sorted(set(d0) | set(d1)):
        if d0.get(dom) != d1.get(dom):
            out.append({"item": f"DVFS {dom}", "old": d0.get(dom), "new": d1.get(dom)})
    for key in ("dvfs_table_ref", "exploration_run_ref"):
        if old.get(key) != new.get(key):
            out.append({"item": key, "old": old.get(key), "new": new.get(key)})
    return out
