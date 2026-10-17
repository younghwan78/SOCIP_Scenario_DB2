"""Previous project report vs this one (RPT-11): risks, power, criteria, basis / policy changes.

Pure function over two frozen snapshots, computed once at report generation and frozen with the new
snapshot (``snapshot["previous"]``), so the comparison never changes after the fact.
"""

from __future__ import annotations

from typing import Any

POWER_DELTA_MIN_MW = 1.0


def _totals(snap: dict[str, Any]) -> dict[str, float]:
    """Registered / recommended total per variant; a variant name used by several scenarios gets the
    scenario as prefix so the rows never collide."""
    rows = [r for r in snap.get("scenarios") or [] if (r.get("power") or {}).get("total_mw") is not None]
    names: dict[str, int] = {}
    for r in rows:
        names[str(r["variant_id"])] = names.get(str(r["variant_id"]), 0) + 1
    out = {}
    for r in rows:
        v = str(r["variant_id"])
        key = f"{r.get('scenario_id')}/{v}" if names[v] > 1 else v
        out[key] = float(r["power"]["total_mw"])
    return out


def _criteria(snap: dict[str, Any]) -> dict[str, Any]:
    cr = snap.get("criteria") or {}
    fps, pw, th = cr.get("fps") or {}, cr.get("power") or {}, cr.get("thermal") or {}
    items = th.get("items") or []
    return {"fps_ok": fps.get("ok"), "fps_total": fps.get("total"), "power_ok": pw.get("ok"), "power_similar": pw.get("similar"),
            "power_over": pw.get("over"), "power_missing": len(pw.get("missing") or []),
            "thermal_reach10": sum(1 for i in items if i.get("reach10")), "thermal_items": len(items),
            "confidence": ((snap.get("conclusion") or {}).get("confidence") or {}).get("grade")}


_BASIS_KEYS = (("throughput_model", "판정 기준"), ("register_baseline", "등록 기준"), ("dvfs_table_ref", "DVFS table"),
               ("engine_rev", "engine"), ("policy_declared", "review policy"))


def report_diff(prev: dict[str, Any], cur: dict[str, Any], prev_meta: dict[str, Any]) -> dict[str, Any]:
    """``prev`` / ``cur``: report snapshots; ``prev_meta``: {id, title, generated_at, status}."""
    reg = cur.get("risk_register") or []
    risks = {
        "new": [r["label"] + " " + r["title"] for r in reg if r.get("trend") == "new"],
        "reopened": [r["label"] + " " + r["title"] for r in reg if r.get("trend") == "reopened"],
        "resolved": [r["label"] + " " + r["title"] for r in reg if r.get("trend") == "resolve_candidate"
                     and any(p.get("key") == r.get("key") and p.get("trend") != "resolve_candidate" for p in prev.get("risk_register") or [])],
    }
    pa, pb = _totals(prev), _totals(cur)
    changed = sorted(({"variant_id": v, "prev_mw": round(pa[v], 1), "cur_mw": round(pb[v], 1), "delta_mw": round(pb[v] - pa[v], 1),
                       "delta_pct": round(100 * (pb[v] - pa[v]) / pa[v], 1) if pa[v] else None}
                      for v in pa.keys() & pb.keys() if abs(pb[v] - pa[v]) >= POWER_DELTA_MIN_MW),
                     key=lambda r: -abs(r["delta_mw"]))
    ca, cb = _criteria(prev), _criteria(cur)
    criteria = [{"item": k, "prev": ca[k], "cur": cb[k]} for k in ca if ca[k] != cb[k]]
    basis = []
    ba, bb = prev.get("basis") or {}, cur.get("basis") or {}
    for key, label in _BASIS_KEYS:
        if ba.get(key) != bb.get(key):
            basis.append({"item": label, "prev": ba.get(key), "cur": bb.get(key)})
    ta = ((prev.get("criteria") or {}).get("power") or {}).get("tolerance_pct")
    tb = ((cur.get("criteria") or {}).get("power") or {}).get("tolerance_pct")
    if ta != tb:
        basis.append({"item": "전과제 허용 %", "prev": ta, "cur": tb})
    cpu_a = {c["variant_id"]: (c.get("summary") or {}).get("tolerance") for c in prev.get("cpu") or []}
    cpu_b = {c["variant_id"]: (c.get("summary") or {}).get("tolerance") for c in cur.get("cpu") or []}
    cpu = [{"variant_id": v, "prev": cpu_a.get(v), "cur": cpu_b.get(v)} for v in sorted(cpu_a.keys() | cpu_b.keys())
           if cpu_a.get(v) != cpu_b.get(v)]
    return {"report": prev_meta, "risks": risks, "power": {"changed": changed[:10], "changed_count": len(changed),
                                                            "added": sorted(pb.keys() - pa.keys()), "removed": sorted(pa.keys() - pb.keys())},
            "criteria": criteria, "basis": basis, "cpu": cpu}
