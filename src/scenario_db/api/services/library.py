"""Library views over reference inputs that are not first-class tables yet."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.services.calibration import is_synthetic
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.models.evidence import Evidence


def sw_timing(db: Session, *, scenario_id: str | None = None) -> dict[str, Any]:
    """Per-variant SW task timing assumptions (node_configs.sw_timing) and measured task timing."""
    q = db.query(ScenarioVariant)
    if scenario_id:
        q = q.filter(ScenarioVariant.scenario_id == scenario_id)
    tasks: dict[tuple[str, str], dict[str, Any]] = {}
    for v in q.order_by(ScenarioVariant.scenario_id, ScenarioVariant.id).all():
        cond = v.design_conditions or {}
        for node, cfg in (v.node_configs or {}).items():
            st = (cfg or {}).get("sw_timing") if isinstance(cfg, dict) else None
            if not isinstance(st, dict):
                continue
            key = (v.scenario_id, str(node))
            row = tasks.setdefault(key, {
                "scenario_id": v.scenario_id, "task": str(node), "variants": 0,
                "min_ms": [], "mean_ms": [], "max_ms": [], "latency_ms": [],
                "value_source": set(), "sw_timing_source": set(), "bitrate_scaled": False,
            })
            row["variants"] += 1
            for k in ("min_ms", "mean_ms", "max_ms"):
                if st.get(k) is not None:
                    row[k].append(float(st[k]))
            lat = st.get("start_latency_mean_ms", st.get("start_jitter_mean_ms"))
            if lat is not None:
                row["latency_ms"].append(float(lat))
            if st.get("value_source"):
                row["value_source"].add(str(st["value_source"]))
            if cond.get("sw_timing_source"):
                row["sw_timing_source"].add(str(cond["sw_timing_source"]))
            if (cfg or {}).get("sw_bitrate_scaling"):
                row["bitrate_scaled"] = True

    def rng(xs: list[float]) -> list[float] | None:
        return [round(min(xs), 3), round(max(xs), 3)] if xs else None

    rows = []
    for r in tasks.values():
        rows.append({
            "scenario_id": r["scenario_id"], "task": r["task"], "variants": r["variants"],
            "min_ms": rng(r["min_ms"]), "mean_ms": rng(r["mean_ms"]), "max_ms": rng(r["max_ms"]),
            "latency_ms": rng(r["latency_ms"]),
            "source": sorted(r["value_source"] | r["sw_timing_source"]) or ["unspecified"],
            "bitrate_scaled": r["bitrate_scaled"],
        })
    measured = []
    mq = db.query(Evidence).filter(Evidence.kind == "evidence.measurement")
    if scenario_id:
        mq = mq.filter(Evidence.scenario_ref == scenario_id)
    for m in mq.all():
        for t in m.sw_task_timing or []:
            if isinstance(t, dict) and t.get("task"):
                measured.append({"evidence_id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref,
                                 "synthetic": is_synthetic(m.provenance), "count": t.get("samples", t.get("count")),
                                 **{k: t.get(k) for k in ("task", "mean_ms", "p95_ms", "max_ms", "count") if k in t}})
    return {"tasks": sorted(rows, key=lambda r: (r["scenario_id"], r["task"])), "measured": measured}


def sw_timing_sets(db: Session, *, scenario_id: str, variant_id: str) -> dict[str, Any]:
    """P2: SW timing of one variant as comparable *sets* — the defined (assumed) table and each measured SW build.

    A set is identified by its source and content, not by the SW profile name: the defined table by a hash of the
    variant's per-node ``sw_timing`` (``정의 #a1b2c3``), a measured set by the evidence SW build + SoC
    (``1.2.3 실측 · 2600``; synthetic fixtures separately). Rows = tasks, Δ% = measured mean vs defined mean.
    """
    from scenario_db.api.services.prediction_basis import _sw_short, soc_short, sw_timing_hash
    from scenario_db.db.models.capability import SwProfile
    from scenario_db.db.repositories.variant_resolution import include_variant_parent_rows, resolve_variant_from_rows
    from scenario_db.exceptions import NotFoundError

    row = db.get(ScenarioVariant, (scenario_id, variant_id))
    if row is None:
        raise NotFoundError(f"variant not found: {scenario_id}/{variant_id}")
    rows = {str(r.id): r for r in include_variant_parent_rows(db, [row]) if str(r.scenario_id) == scenario_id}
    try:
        resolved = resolve_variant_from_rows(rows, scenario_id, variant_id)
    except (LookupError, ValueError):
        resolved = row
    nodes = getattr(resolved, "node_configs", None) or {}
    defined = {str(n): cfg["sw_timing"] for n, cfg in nodes.items() if isinstance(cfg, dict) and isinstance(cfg.get("sw_timing"), dict)}
    digest = sw_timing_hash({"node_configs": nodes})
    sets: list[dict[str, Any]] = []
    values: dict[str, dict[str, dict[str, Any]]] = {}
    if defined:
        sid = f"defined:{digest}"
        sets.append({"id": sid, "label": f"정의 #{digest}", "source": "defined", "sw_ref": None, "soc": None, "synthetic": False,
                     "evidence": 0, "value_source": sorted({str(t.get("value_source") or "unspecified") for t in defined.values()})})
        for task, t in defined.items():
            values.setdefault(task, {})[sid] = {k: t.get(k) for k in ("min_ms", "mean_ms", "max_ms")}
    meas = (db.query(Evidence).filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref == scenario_id,
                                      Evidence.variant_ref == variant_id).all())
    sw_refs = {m.sw_baseline_ref for m in meas if m.sw_baseline_ref}
    socs = {r.id: soc_short(((r.metadata_ or {}).get("compatible_soc") or [None])[0])
            for r in db.query(SwProfile.id, SwProfile.metadata_).filter(SwProfile.id.in_(sw_refs)).all()} if sw_refs else {}
    groups: dict[tuple[str | None, bool], list[Evidence]] = {}
    for m in meas:
        if m.sw_task_timing:
            groups.setdefault((m.sw_baseline_ref, is_synthetic(m.provenance)), []).append(m)
    for (sw_ref, synthetic), evs in sorted(groups.items(), key=lambda kv: (kv[0][1], str(kv[0][0]))):
        soc = socs.get(sw_ref) if sw_ref else None
        sid = f"measured:{sw_ref}:{'syn' if synthetic else 'real'}"
        dates = sorted(str(e.measured_at)[:10] for e in evs if e.measured_at)
        sets.append({"id": sid, "label": f"{_sw_short(sw_ref) or 'SW ?'} {'합성' if synthetic else '실측'}{f' · {soc}' if soc else ''}",
                     "source": "measured", "sw_ref": sw_ref, "soc": soc, "synthetic": synthetic, "evidence": len(evs),
                     "latest": dates[-1] if dates else None})
        per: dict[str, list[dict[str, Any]]] = {}
        for e in evs:
            for t in e.sw_task_timing or []:
                if isinstance(t, dict) and t.get("task"):
                    per.setdefault(str(t["task"]), []).append(t)
        for task, ts in per.items():
            means = [float(t["mean_ms"]) for t in ts if t.get("mean_ms") is not None]
            values.setdefault(task, {})[sid] = {
                "mean_ms": round(sum(means) / len(means), 3) if means else None,
                "p95_ms": max((float(t["p95_ms"]) for t in ts if t.get("p95_ms") is not None), default=None),
                "max_ms": max((float(t["max_ms"]) for t in ts if t.get("max_ms") is not None), default=None),
                "evidence": len(ts)}
    base_id = sets[0]["id"] if sets and sets[0]["source"] == "defined" else None
    tasks = []
    for task in sorted(values):
        v = values[task]
        base = (v.get(base_id) or {}).get("mean_ms") if base_id else None
        for sid, cell in v.items():
            if sid != base_id and base and cell.get("mean_ms") is not None:
                cell["delta_pct"] = round((cell["mean_ms"] - base) / base * 100, 1)
        tasks.append({"task": task, "values": v})
    return {"scenario_id": scenario_id, "variant_id": variant_id, "sets": sets, "tasks": tasks}
