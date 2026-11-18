"""Concurrent scenarios, static composition (review finding S-06, step 1).

Two or more scenario variants that run at the same time (YouTube + voice call, game + audio streaming, …) are
composed from their own Timing Budget reports, without a joint simulation:

- power and BW add up per component (CPU, HW IP, BW, declared domain / assumed loads);
- a DVFS domain shared by several members runs at the highest clock any member needs: every member IP in that
  domain is re-priced at that level's voltage, ``P x (V_shared / V_own)^2`` (the IP's own work is unchanged);
- shared CPU load: the members' CPU busy time per their own frame period, in core-equivalents;
- a pipeline node present in several members (one DPU, one ABOX, one GPU …) is listed as shared: its power is
  the sum of the members' loads, an upper bound when one instance serves both (one display composes both).

Out of scope (stated in ``limits``): contention between members (the same CPU thread / core, BW latency), a domain
load re-priced on its combined work, and a timing re-run at the shared clocks (a higher clock only shortens HW).
"""

from __future__ import annotations

from typing import Any


def _ladder_mv(ladders: dict[str, list[dict[str, Any]]], group: str, mhz: float) -> float | None:
    rows = sorted(ladders.get(group) or [], key=lambda r: float(r.get("mhz") or 0.0))
    for r in rows:
        if float(r.get("mhz") or 0.0) >= mhz - 1e-6 and r.get("mv"):
            return float(r["mv"])
    return float(rows[-1]["mv"]) if rows and rows[-1].get("mv") else None


def compose(members: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """``members`` = [(label, timing budget report)] -> the composed power / BW / DVFS / CPU view."""
    if len(members) < 2:
        raise ValueError("a concurrent set needs at least two members")
    ladders: dict[str, list[dict[str, Any]]] = {}
    for _, r in members:
        for g, rows in ((r.get("dvfs") or {}).get("ladders") or {}).items():
            ladders.setdefault(g, rows)

    # shared DVFS domains: the highest set clock any member needs
    need: dict[str, list[tuple[str, str, float, float]]] = {}
    for label, r in members:
        for ip in r.get("ips") or []:
            g, mhz = ip.get("dvfs_group"), float(ip.get("set_clock_mhz") or 0.0)
            if g and mhz > 0:
                need.setdefault(g, []).append((label, str(ip["node"]), mhz, float(ip.get("voltage_mv") or 0.0)))
    shared_domains = []
    raise_mw: dict[str, float] = {label: 0.0 for label, _ in members}
    for g, rows in sorted(need.items()):
        if len({lab for lab, *_ in rows}) < 2:
            continue
        top = max(m for _, _, m, _ in rows)
        mv = _ladder_mv(ladders, g, top) or max(v for *_, v in rows)
        delta = 0.0
        raised = []
        for label, node, mhz, v in rows:
            ip = next(i for i in (dict(members)[label].get("ips") or []) if i["node"] == node)
            p = float(ip.get("power_mw") or 0.0)
            if v > 0 and mv > v + 1e-9 and p > 0:
                d = p * ((mv / v) ** 2 - 1.0)
                delta += d
                raise_mw[label] += d
                raised.append({"member": label, "node": node, "own_mhz": round(mhz, 1), "own_mv": v, "delta_mw": round(d, 3)})
        shared_domains.append({"group": g, "clock_mhz": round(top, 1), "mv": mv,
                               "members": sorted({lab for lab, *_ in rows}), "raised": raised, "delta_mw": round(delta, 3)})

    rows = []
    totals = {"cpu_mw": 0.0, "hw_mw": 0.0, "bw_mw": 0.0, "dvfs_raise_mw": 0.0, "bw_mbs": 0.0, "cpu_load": 0.0,
              "peak_bw_upper_mbs": 0.0}
    node_members: dict[str, list[str]] = {}
    hw_by_node: dict[str, float] = {}
    for label, r in members:
        p, bw = r.get("power") or {}, r.get("bw") or {}
        period = float(r.get("period_ms") or 0.0)
        load = float(p.get("cpu_busy_ms") or 0.0) / period if period > 0 else 0.0
        row = {"member": label, "scenario_id": r.get("scenario_id"), "variant_id": r.get("variant_id"),
               "verdict": (r.get("verdict") or {}).get("status"), "fps": r.get("fps"),
               "total_mw": float(p.get("total_mw") or 0.0), "cpu_mw": float(p.get("cpu_mw") or 0.0),
               "hw_mw": float(p.get("hw_mw") or 0.0), "bw_mw": float(p.get("bw_mw") or 0.0),
               "bw_mbs": float(bw.get("total_mbs") or 0.0), "cpu_load": round(load, 4),
               "dvfs_raise_mw": round(raise_mw[label], 3)}
        rows.append(row)
        for k in ("cpu_mw", "hw_mw", "bw_mw", "bw_mbs", "cpu_load", "dvfs_raise_mw"):
            totals[k] += row[k]
        totals["peak_bw_upper_mbs"] += float((bw.get("peak") or {}).get("max_stage_mbs") or bw.get("total_mbs") or 0.0)
        for node, mw in (p.get("hw_by_ip") or {}).items():
            node_members.setdefault(node, []).append(label)
            hw_by_node[node] = hw_by_node.get(node, 0.0) + float(mw or 0.0)
        for node in (p.get("assumed_by_ip") or {}):
            node_members.setdefault(node, []).append(label)
    shared_nodes = [{"node": n, "members": m, "mw": round(hw_by_node.get(n, 0.0), 3)}
                    for n, m in sorted(node_members.items()) if len(set(m)) > 1]
    total = totals["cpu_mw"] + totals["hw_mw"] + totals["bw_mw"] + totals["dvfs_raise_mw"]
    failing = [r["member"] for r in rows if r["verdict"] == "fail"]
    notes = []
    if totals["cpu_load"] > 1.0:
        notes.append(f"CPU 부하 합 {totals['cpu_load']:.2f} core-equivalent > 1 (flat CPU 모델 cluster 하나 기준)")
    for s in shared_nodes:
        notes.append(f"{s['node']}: {', '.join(s['members'])}가 같이 사용 — 전력은 합산(한 instance가 둘을 처리하면 상한)")
    return {
        "members": rows,
        "power": {"total_mw": round(total, 2), "cpu_mw": round(totals["cpu_mw"], 2), "hw_mw": round(totals["hw_mw"], 2),
                  "bw_mw": round(totals["bw_mw"], 2), "dvfs_raise_mw": round(totals["dvfs_raise_mw"], 2),
                  "sum_of_members_mw": round(sum(r["total_mw"] for r in rows), 2)},
        "bw": {"total_mbs": round(totals["bw_mbs"], 1), "peak_upper_mbs": round(totals["peak_bw_upper_mbs"], 1)},
        "cpu": {"load_core_eq": round(totals["cpu_load"], 3)},
        "shared_domains": shared_domains,
        "shared_nodes": shared_nodes,
        "verdict": {"status": "fail" if failing else "ok", "failing_members": failing, "notes": notes},
        "limits": ["member 사이 경합(같은 CPU thread/core, BW 지연)은 반영 안 함",
                   "공유 domain 부하(GPU · NPU · ABOX)는 합산만 — 합친 work로 운영점 재선정 안 함",
                   "공유 clock에서 timing 재실행 안 함 (clock이 오르면 HW 시간은 줄기만 함)"],
    }
