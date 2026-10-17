"""Rail-level prediction attribution and SW / latency comparison (CAL-09 · CAL-10 · CAL-11).

The registered prediction has a CPU / IP / BW split; the measurement has rails. To show *which rail*
carries an error, the prediction is attributed onto rail groups:

- IP   per voltage domain: each predicted IP node's power goes to its ``vdd`` (simulation
       ``dvfs_breakdown`` node → vdd, else dvfs_group → vdd). A predicted vdd without its own measured
       rail joins the measured rail with the longest matching prefix (VDD_INTCAM → VDD_INT) and says so.
- CPU  one group (the prediction books CPU per task, not per cluster); measured cluster rails are listed
       so the measured cluster share is visible.
- BW   one group: MIF + DRAM rails vs the BW (DMA) term.
- other rails the scenario model does not cover (prediction 0, flagged ``unmodeled``).

Groups are sorted by |Δ mW| so the first row is the largest contributor to the total error.
"""

from __future__ import annotations

import re
from typing import Any

from scenario_db.comparison.calibration import pct

CPU_CLUSTER_RE = re.compile(r"CPUCL\d_?(DSU|LIT|BIG|MID_?[A-Z0-9]*)?", re.I)


def node_vdd_map(dvfs_breakdown: list[dict[str, Any]] | None) -> tuple[dict[str, str], dict[str, str]]:
    """(node → vdd, dvfs_group → vdd) from a simulation's ``dvfs_breakdown``."""
    nodes: dict[str, str] = {}
    groups: dict[str, str] = {}
    for row in dvfs_breakdown or []:
        if not isinstance(row, dict) or not row.get("vdd"):
            continue
        vdd = str(row["vdd"])
        if row.get("node_id"):
            nodes.setdefault(str(row["node_id"]), vdd)
        if row.get("dvfs_group"):
            groups.setdefault(str(row["dvfs_group"]), vdd)
    return nodes, groups


def ip_power_by_vdd(ips: list[dict[str, Any]] | None, node_vdd: dict[str, str],
                    group_vdd: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Predicted IP power per vdd with the contributing nodes (largest first)."""
    out: dict[str, dict[str, Any]] = {}
    for ip in ips or []:
        node = str(ip.get("node") or "")
        group = str(ip.get("dvfs_group") or "")
        vdd = node_vdd.get(node) or group_vdd.get(group) or (f"VDD_{group}" if group else "VDD_?")
        g = out.setdefault(vdd, {"mw": 0.0, "nodes": []})
        mw = float(ip.get("power_mw") or 0.0)
        g["mw"] += mw
        g["nodes"].append({"node": node, "mw": round(mw, 2), "dvfs_group": group or None,
                           "dvfs_level": ip.get("dvfs_level"), "set_clock_mhz": ip.get("set_clock_mhz")})
    for g in out.values():
        g["mw"] = round(g["mw"], 3)
        g["nodes"].sort(key=lambda n: -n["mw"])
    return out


def _token_re(vdd: str) -> re.Pattern[str]:
    return re.compile(rf"(^|_){re.escape(vdd)}(_|$)", re.I)


def _rail_vdd(rail: str, vdds: list[str]) -> str | None:
    """Longest predicted vdd token found in the measured rail name."""
    hits = [v for v in vdds if _token_re(v).search(rail)]
    return max(hits, key=len) if hits else None


def rail_attribution(rails: list[dict[str, Any]], pred: dict[str, float] | None,
                     ip_by_vdd: dict[str, dict[str, Any]] | None = None,
                     cpu_by_task: dict[str, float] | None = None) -> dict[str, Any]:
    """Rail groups (measured vs attributed prediction), largest |Δ mW| first.

    ``rails``: ``measured_split(...)["rails"]``; ``pred``: {cpu, ip, bw} mW (None = no prediction).
    """
    ip_by_vdd = dict(ip_by_vdd or {})
    groups: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    def group(key: str, category: str, label: str) -> dict[str, Any]:
        return groups.setdefault(key, {"key": key, "label": label, "category": category, "meas_mw": 0.0,
                                       "pred_mw": None, "rails": [], "pred_items": [], "note": None})

    vdds = sorted(ip_by_vdd)
    ip_rails: dict[str, list[dict[str, Any]]] = {}
    for r in rails:
        cat = r["category"]
        if cat == "cpu":
            g = group("cpu", "cpu", "CPU (cluster + DSU)")
        elif cat == "bw":
            g = group("bw", "bw", "BW (MIF + DRAM)")
        elif cat == "ip":
            vdd = _rail_vdd(r["rail"], vdds) or r["rail"]
            g = group(f"ip:{vdd}", "ip", vdd)
            ip_rails.setdefault(vdd, []).append(r)
        else:
            g = group("other", "other", "기타 (모델 범위 밖)")
        g["meas_mw"] += float(r["power_mw"] or 0.0)
        g["rails"].append({"rail": r["rail"], "mw": r["power_mw"]})
    # predicted vdds without a measured rail of their own → longest-prefix measured group
    for vdd, item in ip_by_vdd.items():
        key = f"ip:{vdd}"
        if key not in groups:
            parent = max((v for v in ip_rails if vdd.upper().startswith(v.upper())), key=len, default=None)
            if parent is not None:
                key = f"ip:{parent}"
                notes.append(f"{vdd} 예측은 별도 실측 rail이 없어 {parent} rail에 합산")
            else:
                group(key, "ip", vdd)["note"] = "실측 rail 없음"
        g = groups[key]
        g["pred_mw"] = round((g["pred_mw"] or 0.0) + item["mw"], 3)
        g["pred_items"].extend({"name": n["node"], "mw": n["mw"], "vdd": vdd} for n in item["nodes"])
    if pred is not None:
        unattributed_ip = round(float(pred.get("ip") or 0.0) - sum(i["mw"] for i in ip_by_vdd.values()), 3)
        if ip_by_vdd and abs(unattributed_ip) > 0.5:
            notes.append(f"IP 예측 중 {unattributed_ip:+.1f} mW는 node 분해가 없어 rail 귀속 불가")
        if not ip_by_vdd and pred.get("ip"):
            g = group("ip:(전체)", "ip", "IP (node 분해 없음)")
            g["pred_mw"] = float(pred["ip"])
        group("cpu", "cpu", "CPU (cluster + DSU)")["pred_mw"] = float(pred.get("cpu") or 0.0)
        groups["cpu"]["pred_items"] = [{"name": t, "mw": round(float(v), 2)}
                                       for t, v in sorted((cpu_by_task or {}).items(), key=lambda kv: -kv[1])]
        group("bw", "bw", "BW (MIF + DRAM)")["pred_mw"] = float(pred.get("bw") or 0.0)
        if "other" in groups:
            groups["other"]["pred_mw"] = 0.0
            groups["other"]["note"] = "scenario power model 밖 (GPU · SRAM · ICPU 등)"
    out = []
    for g in groups.values():
        g["meas_mw"] = round(g["meas_mw"], 3)
        g["delta_mw"] = None if g["pred_mw"] is None else round(g["pred_mw"] - g["meas_mw"], 3)
        g["delta_pct"] = pct(g["pred_mw"], g["meas_mw"]) if g["rails"] else None
        g["rails"].sort(key=lambda x: -float(x["mw"] or 0.0))
        g["pred_items"] = g["pred_items"][:12]
        out.append(g)
    out.sort(key=lambda g: -abs(g["delta_mw"] if g["delta_mw"] is not None else g["meas_mw"]))
    total_abs = sum(abs(g["delta_mw"]) for g in out if g["delta_mw"] is not None)
    for g in out:
        g["share_pct"] = (round(100 * abs(g["delta_mw"]) / total_abs, 1)
                          if g["delta_mw"] is not None and total_abs > 0 else None)
    cpu = groups.get("cpu")
    clusters = []
    if cpu and cpu["meas_mw"] > 0:
        for r in cpu["rails"]:
            m = CPU_CLUSTER_RE.search(r["rail"])
            clusters.append({"rail": r["rail"], "cluster": (m.group(0) if m else r["rail"]), "mw": r["mw"],
                             "share_pct": round(100 * float(r["mw"] or 0.0) / cpu["meas_mw"], 1)})
    return {"groups": out, "notes": notes, "cpu_clusters": clusters}


def sw_task_compare(measured: list[dict[str, Any]] | None, assumed: dict[str, dict[str, Any]] | None, *,
                    statistic: str | None, budget_ms: float | None) -> dict[str, Any]:
    """Measured SW task timing vs the Timing Budget assumption used by the prediction (CAL-10).

    Assumed value = the prediction's statistic (min / mean / max) of the defined table; the measured
    p95 is the comparison point (a frame deadline is missed by the tail, not the mean). ``margin_pct``
    = (budget − ms) / budget for both, so a task whose measured tail eats the stage budget stands out.
    """
    stat = statistic if statistic in ("min", "mean", "max") else "mean"
    key = f"{stat}_ms"
    rows = []
    names = list(dict.fromkeys([str(t.get("task")) for t in measured or [] if t.get("task")] + list(assumed or {})))
    meas = {str(t.get("task")): t for t in measured or [] if t.get("task")}
    for name in names:
        m = meas.get(name) or {}
        a = (assumed or {}).get(name) or {}
        a_ms = a.get(key) if a.get(key) is not None else a.get("mean_ms")
        p95 = m.get("p95_ms") if m.get("p95_ms") is not None else m.get("max_ms")
        row = {"task": name, "assumed_ms": a_ms, "assumed_stat": stat if a.get(key) is not None else ("mean" if a_ms is not None else None),
               "mean_ms": m.get("mean_ms"), "p95_ms": p95, "max_ms": m.get("max_ms"),
               "delta_ms": round(p95 - a_ms, 3) if p95 is not None and a_ms is not None else None,
               "delta_pct": pct(p95, a_ms) if p95 is not None and a_ms else None,
               "assumed_margin_pct": round(100 * (budget_ms - a_ms) / budget_ms, 1) if budget_ms and a_ms is not None else None,
               "measured_margin_pct": round(100 * (budget_ms - p95) / budget_ms, 1) if budget_ms and p95 is not None else None,
               "status": None}
        if row["delta_ms"] is None:
            row["status"] = "measured_only" if m else "assumed_only"
        elif row["measured_margin_pct"] is not None and row["measured_margin_pct"] < 0:
            row["status"] = "over_budget"
        elif row["delta_ms"] > 0:
            row["status"] = "under_assumed"   # measured tail longer than the assumption: prediction optimistic
        else:
            row["status"] = "within"
        rows.append(row)
    rows.sort(key=lambda r: -(r["delta_ms"] if r["delta_ms"] is not None else -1e9))
    worst = next((r for r in rows if r["delta_ms"] is not None), None)
    return {"statistic": stat, "budget_ms": budget_ms, "rows": rows,
            "optimistic": sum(1 for r in rows if r["status"] in ("under_assumed", "over_budget")),
            "compared": sum(1 for r in rows if r["delta_ms"] is not None), "worst": worst}


def latency_compare(pred_latency: dict[str, Any] | None, meas_latency: dict[str, Any] | None) -> dict[str, Any] | None:
    """Predicted pipeline latency (video path) vs measured frame latency p95 / mean (CAL-11)."""
    if not pred_latency and not meas_latency:
        return None
    pred_ms = (pred_latency or {}).get("video_ms") or (pred_latency or {}).get("preview_ms")
    p95 = (meas_latency or {}).get("p95")
    mean = (meas_latency or {}).get("mean")
    return {"pred_ms": pred_ms, "meas_p95_ms": p95, "meas_mean_ms": mean,
            "delta_pct": pct(pred_ms, p95 if p95 is not None else mean)}


def clock_compare(ips: list[dict[str, Any]] | None, residency: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Predicted IP clock per dvfs group vs measured residency of the same domain (CAL-11).

    Domains are matched by name (group == domain or class label); groups without a measured
    residency are returned with ``meas_mhz`` None so the column shows what is missing.
    """
    by_group: dict[str, dict[str, Any]] = {}
    for ip in ips or []:
        g = str(ip.get("dvfs_group") or "")
        if not g:
            continue
        cur = by_group.setdefault(g, {"group": g, "pred_mhz": 0.0, "dvfs_level": ip.get("dvfs_level"), "nodes": 0})
        cur["pred_mhz"] = max(cur["pred_mhz"], float(ip.get("set_clock_mhz") or 0.0))
        cur["nodes"] += 1
    doms = {}
    for d in (residency or {}).get("domains") or []:
        for name in (d.get("domain"), d.get("class_label")):
            if name:
                doms.setdefault(str(name).upper(), d)
    out = []
    for g, row in sorted(by_group.items()):
        d = doms.get(g.upper())
        stats = (d.get("active") or d.get("wall")) if d else None
        meas = stats.get("mean_mhz") if stats else None
        mode = stats.get("p50_mhz") if stats else None
        out.append(row | {"pred_mhz": round(row["pred_mhz"], 1), "meas_mhz": meas, "meas_p50_mhz": mode,
                          "delta_pct": pct(row["pred_mhz"], meas) if meas else None})
    return out
